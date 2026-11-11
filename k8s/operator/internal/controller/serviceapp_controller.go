// Package controller reconciles ServiceApp objects into Deployments and Services.
package controller

import (
	"context"
	"fmt"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/controller/controllerutil"
	logf "sigs.k8s.io/controller-runtime/pkg/log"

	homeopsv1 "github.com/jackaI1/home-server-ops/k8s/operator/api/v1alpha1"
)

// DefaultRequeueAfter is how often a ServiceApp is checked again, so a service
// that breaks later still gets its HealthCheck condition updated.
const DefaultRequeueAfter = 30 * time.Second

// Condition reasons.
const (
	ReasonRolloutComplete     = "RolloutComplete"
	ReasonRolloutInProgress   = "RolloutInProgress"
	ReasonDeadlineExceeded    = "ProgressDeadlineExceeded"
	ReasonHealthCheckPassing  = "HealthCheckPassing"
	ReasonHealthCheckFailed   = "HealthCheckFailed"
	maxConditionMessageLength = 256
)

// ServiceAppReconciler makes the Deployment and Service match a ServiceApp,
// then records whether the rollout finished and whether the health check passes.
type ServiceAppReconciler struct {
	client.Client
	Scheme       *runtime.Scheme
	Prober       HealthProber
	RequeueAfter time.Duration
}

// +kubebuilder:rbac:groups=homeops.local,resources=serviceapps,verbs=get;list;watch
// +kubebuilder:rbac:groups=homeops.local,resources=serviceapps/status,verbs=get;update;patch
// +kubebuilder:rbac:groups=apps,resources=deployments,verbs=get;list;watch;create;update;patch;delete
// +kubebuilder:rbac:groups="",resources=services,verbs=get;list;watch;create;update;patch;delete

// Reconcile implements the controller loop for one ServiceApp.
func (r *ServiceAppReconciler) Reconcile(ctx context.Context, req ctrl.Request) (ctrl.Result, error) {
	log := logf.FromContext(ctx)

	var app homeopsv1.ServiceApp
	if err := r.Get(ctx, req.NamespacedName, &app); err != nil {
		return ctrl.Result{}, client.IgnoreNotFound(err)
	}

	deploy, err := r.applyDeployment(ctx, &app)
	if err != nil {
		return ctrl.Result{}, fmt.Errorf("apply deployment: %w", err)
	}
	if err := r.applyService(ctx, &app); err != nil {
		return ctrl.Result{}, fmt.Errorf("apply service: %w", err)
	}

	probeErr := r.Prober.Check(ctx, HealthURL(&app))
	updateStatus(&app, deploy, probeErr)
	if err := r.Status().Update(ctx, &app); err != nil {
		return ctrl.Result{}, fmt.Errorf("update status: %w", err)
	}
	log.V(1).Info("reconciled ServiceApp", "version", app.Spec.Version, "healthy", probeErr == nil)

	requeue := r.RequeueAfter
	if requeue == 0 {
		requeue = DefaultRequeueAfter
	}
	return ctrl.Result{RequeueAfter: requeue}, nil
}

// applyDeployment creates or updates the Deployment and returns its latest state.
func (r *ServiceAppReconciler) applyDeployment(ctx context.Context, app *homeopsv1.ServiceApp) (*appsv1.Deployment, error) {
	desired := BuildDeployment(app)
	deploy := &appsv1.Deployment{ObjectMeta: metav1.ObjectMeta{Name: desired.Name, Namespace: desired.Namespace}}
	_, err := controllerutil.CreateOrUpdate(ctx, r.Client, deploy, func() error {
		deploy.Labels = desired.Labels
		deploy.Spec = desired.Spec
		return controllerutil.SetControllerReference(app, deploy, r.Scheme)
	})
	return deploy, err
}

func (r *ServiceAppReconciler) applyService(ctx context.Context, app *homeopsv1.ServiceApp) error {
	desired := BuildService(app)
	svc := &corev1.Service{ObjectMeta: metav1.ObjectMeta{Name: desired.Name, Namespace: desired.Namespace}}
	_, err := controllerutil.CreateOrUpdate(ctx, r.Client, svc, func() error {
		svc.Labels = desired.Labels
		svc.Spec.Selector = desired.Spec.Selector
		svc.Spec.Ports = desired.Spec.Ports
		svc.Spec.Type = corev1.ServiceTypeClusterIP
		return controllerutil.SetControllerReference(app, svc, r.Scheme)
	})
	return err
}

// updateStatus sets the observed fields and both conditions on app.
func updateStatus(app *homeopsv1.ServiceApp, deploy *appsv1.Deployment, probeErr error) {
	app.Status.ObservedGeneration = app.Generation
	app.Status.DeployedVersion = app.Spec.Version
	app.Status.ReadyReplicas = deploy.Status.ReadyReplicas
	meta.SetStatusCondition(&app.Status.Conditions, rolloutCondition(app, deploy))
	meta.SetStatusCondition(&app.Status.Conditions, healthCondition(app, probeErr))
}

// rolloutCondition reports whether the Deployment has finished the requested rollout.
func rolloutCondition(app *homeopsv1.ServiceApp, deploy *appsv1.Deployment) metav1.Condition {
	want := DesiredReplicas(app)
	cond := metav1.Condition{Type: homeopsv1.ConditionReady, Status: metav1.ConditionTrue, Reason: ReasonRolloutComplete,
		Message: fmt.Sprintf("%s is running on %d of %d replicas", ImageRef(app), deploy.Status.AvailableReplicas, want)}
	switch {
	case deploy.Status.ObservedGeneration < deploy.Generation:
		cond.Status, cond.Reason = metav1.ConditionFalse, ReasonRolloutInProgress
		cond.Message = "waiting for the Deployment controller to see the new spec"
	case hasProgressDeadlineExceeded(deploy):
		cond.Status, cond.Reason = metav1.ConditionFalse, ReasonDeadlineExceeded
		cond.Message = "the new pods did not become ready before the progress deadline"
	case deploy.Status.UpdatedReplicas < want || deploy.Status.AvailableReplicas < want:
		cond.Status, cond.Reason = metav1.ConditionFalse, ReasonRolloutInProgress
		cond.Message = fmt.Sprintf("%d of %d replicas available", deploy.Status.AvailableReplicas, want)
	}
	return cond
}

func hasProgressDeadlineExceeded(deploy *appsv1.Deployment) bool {
	for _, c := range deploy.Status.Conditions {
		if c.Type == appsv1.DeploymentProgressing && c.Status == corev1.ConditionFalse &&
			c.Reason == "ProgressDeadlineExceeded" {
			return true
		}
	}
	return false
}

// healthCondition reports the result of the HTTP health check.
func healthCondition(app *homeopsv1.ServiceApp, probeErr error) metav1.Condition {
	if probeErr == nil {
		return metav1.Condition{Type: homeopsv1.ConditionHealthCheck, Status: metav1.ConditionTrue,
			Reason: ReasonHealthCheckPassing, Message: "GET " + HealthURL(app) + " returned 2xx"}
	}
	msg := probeErr.Error()
	if len(msg) > maxConditionMessageLength {
		msg = msg[:maxConditionMessageLength]
	}
	return metav1.Condition{Type: homeopsv1.ConditionHealthCheck, Status: metav1.ConditionFalse,
		Reason: ReasonHealthCheckFailed, Message: msg}
}

// SetupWithManager registers the controller and watches the objects it owns.
func (r *ServiceAppReconciler) SetupWithManager(mgr ctrl.Manager) error {
	return ctrl.NewControllerManagedBy(mgr).
		For(&homeopsv1.ServiceApp{}).
		Owns(&appsv1.Deployment{}).
		Owns(&corev1.Service{}).
		Complete(r)
}
