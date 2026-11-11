package controller

import (
	"context"
	"errors"
	"os"
	"path/filepath"
	"testing"
	"time"

	appsv1 "k8s.io/api/apps/v1"
	"k8s.io/apimachinery/pkg/api/meta"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
	"k8s.io/apimachinery/pkg/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/client"
	"sigs.k8s.io/controller-runtime/pkg/envtest"

	homeopsv1 "github.com/jackaI1/home-server-ops/k8s/operator/api/v1alpha1"
)

// fakeProber returns whatever error the test sets, so the health result is known.
type fakeProber struct {
	err   error
	calls int
}

func (f *fakeProber) Check(context.Context, string) error {
	f.calls++
	return f.err
}

// startEnvtest runs a real kube-apiserver and etcd. The binaries come from
// KUBEBUILDER_ASSETS, which CI sets with setup-envtest. The test is skipped
// when they are missing, so `go test` on a laptop without them still passes.
func startEnvtest(t *testing.T) (client.Client, func()) {
	t.Helper()
	if os.Getenv("KUBEBUILDER_ASSETS") == "" {
		t.Skip("KUBEBUILDER_ASSETS is not set; run `make test` to fetch envtest binaries")
	}
	env := &envtest.Environment{
		CRDDirectoryPaths:     []string{filepath.Join("..", "..", "chart", "crds")},
		ErrorIfCRDPathMissing: true,
	}
	cfg, err := env.Start()
	if err != nil {
		t.Fatalf("start envtest: %v", err)
	}
	scheme := runtime.NewScheme()
	if err := clientgoscheme.AddToScheme(scheme); err != nil {
		t.Fatal(err)
	}
	if err := homeopsv1.AddToScheme(scheme); err != nil {
		t.Fatal(err)
	}
	c, err := client.New(cfg, client.Options{Scheme: scheme})
	if err != nil {
		t.Fatalf("create client: %v", err)
	}
	return c, func() { _ = env.Stop() }
}

func reconcileOnce(t *testing.T, r *ServiceAppReconciler, name string) {
	t.Helper()
	_, err := r.Reconcile(context.Background(), ctrl.Request{NamespacedName: client.ObjectKey{Namespace: "default", Name: name}})
	if err != nil {
		t.Fatalf("reconcile: %v", err)
	}
}

func getApp(t *testing.T, c client.Client, name string) *homeopsv1.ServiceApp {
	t.Helper()
	var app homeopsv1.ServiceApp
	if err := c.Get(context.Background(), client.ObjectKey{Namespace: "default", Name: name}, &app); err != nil {
		t.Fatalf("get ServiceApp: %v", err)
	}
	return &app
}

func condition(app *homeopsv1.ServiceApp, typ string) *metav1.Condition {
	return meta.FindStatusCondition(app.Status.Conditions, typ)
}

// TestReconcilerEnvtest walks one ServiceApp through its life: create, roll out,
// bump the version, and fail a health check. It runs against a real API server,
// so CRD validation, owner references and the status subresource are real.
func TestReconcilerEnvtest(t *testing.T) {
	c, stop := startEnvtest(t)
	defer stop()
	ctx := context.Background()
	prober := &fakeProber{}
	r := &ServiceAppReconciler{Client: c, Scheme: c.Scheme(), Prober: prober, RequeueAfter: time.Second}

	app := &homeopsv1.ServiceApp{
		ObjectMeta: metav1.ObjectMeta{Name: "web", Namespace: "default"},
		Spec:       homeopsv1.ServiceAppSpec{Image: "nginx", Version: "1.27-alpine", HealthPath: "/"},
	}
	if err := c.Create(ctx, app); err != nil {
		t.Fatalf("create ServiceApp: %v", err)
	}

	t.Run("creates the Deployment and Service", func(t *testing.T) {
		reconcileOnce(t, r, "web")
		var deploy appsv1.Deployment
		if err := c.Get(ctx, client.ObjectKey{Namespace: "default", Name: "web"}, &deploy); err != nil {
			t.Fatalf("get Deployment: %v", err)
		}
		if got := deploy.Spec.Template.Spec.Containers[0].Image; got != "nginx:1.27-alpine" {
			t.Fatalf("image = %q", got)
		}
		if len(deploy.OwnerReferences) != 1 || deploy.OwnerReferences[0].Kind != "ServiceApp" {
			t.Fatalf("owner references = %+v", deploy.OwnerReferences)
		}
		got := getApp(t, c, "web")
		if ready := condition(got, homeopsv1.ConditionReady); ready == nil || ready.Status != metav1.ConditionFalse {
			t.Fatalf("Ready before rollout = %+v", ready)
		}
		if hc := condition(got, homeopsv1.ConditionHealthCheck); hc == nil || hc.Status != metav1.ConditionTrue {
			t.Fatalf("HealthCheck with passing prober = %+v", hc)
		}
	})

	t.Run("reports Ready once the Deployment finishes the rollout", func(t *testing.T) {
		var deploy appsv1.Deployment
		if err := c.Get(ctx, client.ObjectKey{Namespace: "default", Name: "web"}, &deploy); err != nil {
			t.Fatal(err)
		}
		// There is no kube-controller-manager in envtest, so the test plays its part.
		deploy.Status = appsv1.DeploymentStatus{
			ObservedGeneration: deploy.Generation, Replicas: 1, UpdatedReplicas: 1,
			AvailableReplicas: 1, ReadyReplicas: 1,
		}
		if err := c.Status().Update(ctx, &deploy); err != nil {
			t.Fatalf("update Deployment status: %v", err)
		}
		reconcileOnce(t, r, "web")
		got := getApp(t, c, "web")
		if ready := condition(got, homeopsv1.ConditionReady); ready == nil || ready.Status != metav1.ConditionTrue {
			t.Fatalf("Ready after rollout = %+v", ready)
		}
		if got.Status.ReadyReplicas != 1 {
			t.Fatalf("readyReplicas = %d", got.Status.ReadyReplicas)
		}
	})

	t.Run("bumping the version updates the image and the rollout", func(t *testing.T) {
		got := getApp(t, c, "web")
		got.Spec.Version = "1.28-alpine"
		if err := c.Update(ctx, got); err != nil {
			t.Fatalf("update ServiceApp: %v", err)
		}
		reconcileOnce(t, r, "web")
		var deploy appsv1.Deployment
		if err := c.Get(ctx, client.ObjectKey{Namespace: "default", Name: "web"}, &deploy); err != nil {
			t.Fatal(err)
		}
		if image := deploy.Spec.Template.Spec.Containers[0].Image; image != "nginx:1.28-alpine" {
			t.Fatalf("image after bump = %q", image)
		}
		updated := getApp(t, c, "web")
		if updated.Status.DeployedVersion != "1.28-alpine" {
			t.Fatalf("deployedVersion = %q", updated.Status.DeployedVersion)
		}
		// The Deployment has a new generation the status has not caught up with yet.
		if ready := condition(updated, homeopsv1.ConditionReady); ready == nil || ready.Status != metav1.ConditionFalse {
			t.Fatalf("Ready during the new rollout = %+v", ready)
		}
	})

	t.Run("a failing health check sets HealthCheck to False", func(t *testing.T) {
		prober.err = errors.New("GET http://web.default.svc:80/ returned 503")
		defer func() { prober.err = nil }()
		reconcileOnce(t, r, "web")
		got := getApp(t, c, "web")
		hc := condition(got, homeopsv1.ConditionHealthCheck)
		if hc == nil || hc.Status != metav1.ConditionFalse || hc.Reason != ReasonHealthCheckFailed {
			t.Fatalf("HealthCheck after failure = %+v", hc)
		}
		if prober.calls == 0 {
			t.Fatal("the prober was never called")
		}
	})

	t.Run("a deleted ServiceApp is not an error", func(t *testing.T) {
		if err := c.Delete(ctx, app); err != nil {
			t.Fatal(err)
		}
		_, err := r.Reconcile(ctx, ctrl.Request{NamespacedName: client.ObjectKey{Namespace: "default", Name: "web"}})
		if err != nil {
			t.Fatalf("reconcile of a missing object: %v", err)
		}
	})
}
