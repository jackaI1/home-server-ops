// Command manager runs the ServiceApp operator. It watches ServiceApp objects and
// keeps a Deployment and a Service for each one.
package main

import (
	"flag"
	"os"
	"time"

	"k8s.io/apimachinery/pkg/runtime"
	utilruntime "k8s.io/apimachinery/pkg/util/runtime"
	clientgoscheme "k8s.io/client-go/kubernetes/scheme"
	ctrl "sigs.k8s.io/controller-runtime"
	"sigs.k8s.io/controller-runtime/pkg/healthz"
	logf "sigs.k8s.io/controller-runtime/pkg/log"
	"sigs.k8s.io/controller-runtime/pkg/log/zap"
	metricsserver "sigs.k8s.io/controller-runtime/pkg/metrics/server"

	homeopsv1 "github.com/jackaI1/home-server-ops/k8s/operator/api/v1alpha1"
	"github.com/jackaI1/home-server-ops/k8s/operator/internal/controller"
)

var scheme = runtime.NewScheme()

func init() {
	utilruntime.Must(clientgoscheme.AddToScheme(scheme))
	utilruntime.Must(homeopsv1.AddToScheme(scheme))
}

func main() {
	var metricsAddr, probeAddr string
	var enableLeaderElection bool
	var requeueAfter time.Duration
	flag.StringVar(&metricsAddr, "metrics-bind-address", ":8080", "address for the metrics endpoint")
	flag.StringVar(&probeAddr, "health-probe-bind-address", ":8081", "address for the /healthz and /readyz probes")
	flag.BoolVar(&enableLeaderElection, "leader-elect", false, "run one active manager when several replicas exist")
	flag.DurationVar(&requeueAfter, "requeue-after", controller.DefaultRequeueAfter, "how often to re-check each ServiceApp")
	flag.Parse()

	logf.SetLogger(zap.New(zap.UseDevMode(false)))
	log := logf.Log.WithName("setup")

	mgr, err := ctrl.NewManager(ctrl.GetConfigOrDie(), ctrl.Options{
		Scheme:                 scheme,
		Metrics:                metricsserver.Options{BindAddress: metricsAddr},
		HealthProbeBindAddress: probeAddr,
		LeaderElection:         enableLeaderElection,
		LeaderElectionID:       "serviceapp-operator.homeops.local",
	})
	if err != nil {
		log.Error(err, "unable to start manager")
		os.Exit(1)
	}

	reconciler := &controller.ServiceAppReconciler{
		Client:       mgr.GetClient(),
		Scheme:       mgr.GetScheme(),
		Prober:       controller.NewHTTPProber(),
		RequeueAfter: requeueAfter,
	}
	if err := reconciler.SetupWithManager(mgr); err != nil {
		log.Error(err, "unable to create controller", "controller", "ServiceApp")
		os.Exit(1)
	}
	if err := mgr.AddHealthzCheck("healthz", healthz.Ping); err != nil {
		log.Error(err, "unable to set up health check")
		os.Exit(1)
	}
	if err := mgr.AddReadyzCheck("readyz", healthz.Ping); err != nil {
		log.Error(err, "unable to set up ready check")
		os.Exit(1)
	}

	log.Info("starting manager")
	if err := mgr.Start(ctrl.SetupSignalHandler()); err != nil {
		log.Error(err, "problem running manager")
		os.Exit(1)
	}
}
