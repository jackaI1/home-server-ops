// Package v1alpha1 holds the ServiceApp API that the operator serves.
// +kubebuilder:object:generate=true
// +groupName=homeops.local
package v1alpha1

import (
	"k8s.io/apimachinery/pkg/runtime/schema"
	"sigs.k8s.io/controller-runtime/pkg/scheme"
)

// GroupVersion is the API group and version for ServiceApp objects.
var GroupVersion = schema.GroupVersion{Group: "homeops.local", Version: "v1alpha1"}

// SchemeBuilder registers the types in this package with a runtime.Scheme.
var SchemeBuilder = &scheme.Builder{GroupVersion: GroupVersion}

// AddToScheme adds ServiceApp and its list type to a scheme.
var AddToScheme = SchemeBuilder.AddToScheme
