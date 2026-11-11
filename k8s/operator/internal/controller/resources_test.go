package controller

import (
	"errors"
	"testing"

	appsv1 "k8s.io/api/apps/v1"
	corev1 "k8s.io/api/core/v1"
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"

	homeopsv1 "github.com/jackaI1/home-server-ops/k8s/operator/api/v1alpha1"
)

func sampleApp() *homeopsv1.ServiceApp {
	replicas := int32(2)
	return &homeopsv1.ServiceApp{
		ObjectMeta: metav1.ObjectMeta{Name: "web", Namespace: "home", Generation: 3},
		Spec: homeopsv1.ServiceAppSpec{
			Image:      "nginx",
			Version:    "1.27-alpine",
			Port:       8080,
			HealthPath: "/healthz",
			Replicas:   &replicas,
		},
	}
}

func TestImageRefCombinesImageAndVersion(t *testing.T) {
	if got := ImageRef(sampleApp()); got != "nginx:1.27-alpine" {
		t.Fatalf("ImageRef = %q", got)
	}
}

func TestHealthURLUsesServiceNameAndPath(t *testing.T) {
	app := sampleApp()
	if got := HealthURL(app); got != "http://web.home.svc:80/healthz" {
		t.Fatalf("HealthURL = %q", got)
	}
	app.Spec.HealthPath = "ready"
	if got := HealthURL(app); got != "http://web.home.svc:80/ready" {
		t.Fatalf("HealthURL without leading slash = %q", got)
	}
	app.Spec.HealthPath = ""
	if got := HealthURL(app); got != "http://web.home.svc:80/" {
		t.Fatalf("HealthURL with empty path = %q", got)
	}
}

func TestDesiredReplicasDefaultsToOne(t *testing.T) {
	app := sampleApp()
	app.Spec.Replicas = nil
	if got := DesiredReplicas(app); got != 1 {
		t.Fatalf("DesiredReplicas(nil) = %d, want 1", got)
	}
}

func TestBuildDeploymentMatchesSpec(t *testing.T) {
	deploy := BuildDeployment(sampleApp())
	if deploy.Name != "web" || deploy.Namespace != "home" {
		t.Fatalf("name/namespace = %s/%s", deploy.Namespace, deploy.Name)
	}
	if *deploy.Spec.Replicas != 2 {
		t.Fatalf("replicas = %d", *deploy.Spec.Replicas)
	}
	c := deploy.Spec.Template.Spec.Containers[0]
	if c.Image != "nginx:1.27-alpine" {
		t.Fatalf("image = %q", c.Image)
	}
	if c.Ports[0].ContainerPort != 8080 {
		t.Fatalf("container port = %d", c.Ports[0].ContainerPort)
	}
	if c.ReadinessProbe == nil || c.ReadinessProbe.HTTPGet.Path != "/healthz" {
		t.Fatalf("readiness probe does not use the health path: %+v", c.ReadinessProbe)
	}
	if deploy.Spec.Selector.MatchLabels["app.kubernetes.io/name"] != "web" {
		t.Fatalf("selector labels = %v", deploy.Spec.Selector.MatchLabels)
	}
}

func TestBuildServiceRoutesPortEightyToContainer(t *testing.T) {
	svc := BuildService(sampleApp())
	if svc.Spec.Type != "" && svc.Spec.Type != corev1.ServiceTypeClusterIP {
		t.Fatalf("type = %s", svc.Spec.Type)
	}
	p := svc.Spec.Ports[0]
	if p.Port != 80 || p.TargetPort.IntValue() != 8080 {
		t.Fatalf("port mapping = %d -> %s", p.Port, p.TargetPort.String())
	}
}

func TestRolloutConditionTable(t *testing.T) {
	app := sampleApp() // generation 3, wants 2 replicas
	cases := []struct {
		name   string
		deploy appsv1.DeploymentStatus
		gen    int64
		status metav1.ConditionStatus
		reason string
	}{
		{"stale generation", appsv1.DeploymentStatus{ObservedGeneration: 2}, 3,
			metav1.ConditionFalse, ReasonRolloutInProgress},
		{"half available", appsv1.DeploymentStatus{ObservedGeneration: 3, UpdatedReplicas: 2, AvailableReplicas: 1}, 3,
			metav1.ConditionFalse, ReasonRolloutInProgress},
		{"deadline exceeded", appsv1.DeploymentStatus{ObservedGeneration: 3, UpdatedReplicas: 2, AvailableReplicas: 1,
			Conditions: []appsv1.DeploymentCondition{{Type: appsv1.DeploymentProgressing,
				Status: corev1.ConditionFalse, Reason: ReasonDeadlineExceeded}}}, 3,
			metav1.ConditionFalse, ReasonDeadlineExceeded},
		{"complete", appsv1.DeploymentStatus{ObservedGeneration: 3, UpdatedReplicas: 2, AvailableReplicas: 2}, 3,
			metav1.ConditionTrue, ReasonRolloutComplete},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			deploy := &appsv1.Deployment{ObjectMeta: metav1.ObjectMeta{Generation: tc.gen}, Status: tc.deploy}
			cond := rolloutCondition(app, deploy)
			if cond.Status != tc.status || cond.Reason != tc.reason {
				t.Fatalf("got %s/%s, want %s/%s (%s)", cond.Status, cond.Reason, tc.status, tc.reason, cond.Message)
			}
		})
	}
}

func TestHealthConditionReportsFailure(t *testing.T) {
	app := sampleApp()
	ok := healthCondition(app, nil)
	if ok.Status != metav1.ConditionTrue || ok.Reason != ReasonHealthCheckPassing {
		t.Fatalf("passing check = %+v", ok)
	}
	bad := healthCondition(app, errors.New("GET http://web.home.svc:80/healthz returned 404"))
	if bad.Status != metav1.ConditionFalse || bad.Reason != ReasonHealthCheckFailed {
		t.Fatalf("failing check = %+v", bad)
	}
	if bad.Message == "" {
		t.Fatal("failing check has no message")
	}
}

func TestHealthConditionTruncatesLongErrors(t *testing.T) {
	long := make([]byte, 1000)
	for i := range long {
		long[i] = 'x'
	}
	cond := healthCondition(sampleApp(), errors.New(string(long)))
	if len(cond.Message) != maxConditionMessageLength {
		t.Fatalf("message length = %d", len(cond.Message))
	}
}
