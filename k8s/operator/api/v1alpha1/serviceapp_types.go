package v1alpha1

import (
	metav1 "k8s.io/apimachinery/pkg/apis/meta/v1"
)

// Condition types reported in ServiceApp.status.conditions.
const (
	// ConditionReady is True when the Deployment has finished rolling out the
	// requested version.
	ConditionReady = "Ready"
	// ConditionHealthCheck is True when the health path answers with a 2xx
	// status through the Service. It is False when the check fails.
	ConditionHealthCheck = "HealthCheck"
)

// ServiceAppSpec describes one home server service: what to run and how to check it.
type ServiceAppSpec struct {
	// Image is the container image without a tag, for example nginx.
	Image string `json:"image"`
	// Version is the image tag to run, for example 1.27-alpine.
	Version string `json:"version"`
	// Port is the port the container listens on.
	// +kubebuilder:default=80
	// +kubebuilder:validation:Minimum=1
	// +kubebuilder:validation:Maximum=65535
	Port int32 `json:"port,omitempty"`
	// HealthPath is the HTTP path the operator checks, for example /healthz.
	// +kubebuilder:default="/"
	HealthPath string `json:"healthPath,omitempty"`
	// Replicas is the number of pods to keep running.
	// +kubebuilder:default=1
	// +kubebuilder:validation:Minimum=0
	Replicas *int32 `json:"replicas,omitempty"`
}

// ServiceAppStatus reports what the operator last saw.
type ServiceAppStatus struct {
	// ObservedGeneration is the spec generation the operator last acted on.
	ObservedGeneration int64 `json:"observedGeneration,omitempty"`
	// DeployedVersion is the image tag that the Deployment was last set to run.
	DeployedVersion string `json:"deployedVersion,omitempty"`
	// ReadyReplicas is the number of pods that passed their readiness probe.
	ReadyReplicas int32 `json:"readyReplicas,omitempty"`
	// Conditions holds the Ready and HealthCheck conditions.
	// +listType=map
	// +listMapKey=type
	// +optional
	Conditions []metav1.Condition `json:"conditions,omitempty"`
}

// +kubebuilder:object:root=true
// +kubebuilder:subresource:status
// +kubebuilder:printcolumn:name="Version",type=string,JSONPath=`.spec.version`
// +kubebuilder:printcolumn:name="Ready",type=string,JSONPath=`.status.conditions[?(@.type=="Ready")].status`
// +kubebuilder:printcolumn:name="Health",type=string,JSONPath=`.status.conditions[?(@.type=="HealthCheck")].status`
// +kubebuilder:printcolumn:name="Age",type=date,JSONPath=`.metadata.creationTimestamp`

// ServiceApp is the Schema for the serviceapps API.
type ServiceApp struct {
	metav1.TypeMeta   `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty"`

	Spec   ServiceAppSpec   `json:"spec,omitempty"`
	Status ServiceAppStatus `json:"status,omitempty"`
}

// +kubebuilder:object:root=true

// ServiceAppList contains a list of ServiceApp.
type ServiceAppList struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ListMeta `json:"metadata,omitempty"`
	Items           []ServiceApp `json:"items"`
}

func init() {
	SchemeBuilder.Register(&ServiceApp{}, &ServiceAppList{})
}
