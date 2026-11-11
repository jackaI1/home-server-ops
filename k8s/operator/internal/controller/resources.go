package controller

import (
	"fmt"
	"strings"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	"k8s.io/apimachinery/pkg/api/resource"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/util/intstr"

	homeopsv1 "github.com/jackaI1/home-server-ops/k8s/operator/api/v1alpha1"
)

// ServicePort is the port the Service exposes inside the cluster.
const ServicePort int32 = 80

// Defaults used when a ServiceApp leaves a field empty.
const (
	defaultContainerPort int32 = 80
	defaultHealthPath          = "/"
	defaultReplicas      int32 = 1
)

// ImageRef returns the image and tag the Deployment runs, for example nginx:1.27-alpine.
func ImageRef(app *homeopsv1.ServiceApp) string {
	return fmt.Sprintf("%s:%s", app.Spec.Image, app.Spec.Version)
}

// HealthURL is the address the operator checks: the Service name, the health path.
func HealthURL(app *homeopsv1.ServiceApp) string {
	path := app.Spec.HealthPath
	if path == "" {
		path = defaultHealthPath
	}
	if !strings.HasPrefix(path, "/") {
		path = "/" + path
	}
	return fmt.Sprintf("http://%s.%s.svc:%d%s", app.Name, app.Namespace, ServicePort, path)
}

// DesiredReplicas returns the replica count, or the default when unset.
func DesiredReplicas(app *homeopsv1.ServiceApp) int32 {
	if app.Spec.Replicas == nil {
		return defaultReplicas
	}
	return *app.Spec.Replicas
}

func containerPort(app *homeopsv1.ServiceApp) int32 {
	if app.Spec.Port == 0 {
		return defaultContainerPort
	}
	return app.Spec.Port
}

func labelsFor(app *homeopsv1.ServiceApp) map[string]string {
	return map[string]string{
		"app.kubernetes.io/name":       app.Name,
		"app.kubernetes.io/managed-by": "serviceapp-operator",
	}
}

// BuildDeployment returns the Deployment the ServiceApp should have.
// The readiness probe uses the same health path the operator checks.
func BuildDeployment(app *homeopsv1.ServiceApp) *appsv1.Deployment {
	labels := labelsFor(app)
	port := containerPort(app)
	path := app.Spec.HealthPath
	if path == "" {
		path = defaultHealthPath
	}
	return &appsv1.Deployment{
		ObjectMeta: metav1.ObjectMeta{Name: app.Name, Namespace: app.Namespace, Labels: labels},
		Spec: appsv1.DeploymentSpec{
			Replicas: ptr(DesiredReplicas(app)),
			Selector: &metav1.LabelSelector{MatchLabels: labels},
			Template: corev1.PodTemplateSpec{
				ObjectMeta: metav1.ObjectMeta{Labels: labels},
				Spec: corev1.PodSpec{
					Containers: []corev1.Container{{
						Name:  "service",
						Image: ImageRef(app),
						Ports: []corev1.ContainerPort{{Name: "http", ContainerPort: port}},
						ReadinessProbe: &corev1.Probe{
							ProbeHandler: corev1.ProbeHandler{
								HTTPGet: &corev1.HTTPGetAction{Path: path, Port: intstr.FromInt32(port)},
							},
							PeriodSeconds:    10,
							FailureThreshold: 3,
						},
						Resources: corev1.ResourceRequirements{
							Limits: corev1.ResourceList{
								corev1.ResourceMemory: resource.MustParse("256Mi"),
								corev1.ResourceCPU:    resource.MustParse("500m"),
							},
						},
					}},
				},
			},
		},
	}
}

// BuildService returns the ClusterIP Service that routes to the Deployment's pods.
func BuildService(app *homeopsv1.ServiceApp) *corev1.Service {
	return &corev1.Service{
		ObjectMeta: metav1.ObjectMeta{Name: app.Name, Namespace: app.Namespace, Labels: labelsFor(app)},
		Spec: corev1.ServiceSpec{
			Selector: labelsFor(app),
			Ports: []corev1.ServicePort{{
				Name:       "http",
				Port:       ServicePort,
				TargetPort: intstr.FromInt32(containerPort(app)),
			}},
		},
	}
}

func ptr[T any](v T) *T {
	return &v
}
