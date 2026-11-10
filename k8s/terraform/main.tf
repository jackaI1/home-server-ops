provider "kubernetes" {
  config_path    = var.kubeconfig_path
  config_context = var.kube_context == "" ? null : var.kube_context
}

provider "helm" {
  kubernetes = {
    config_path    = var.kubeconfig_path
    config_context = var.kube_context == "" ? null : var.kube_context
  }
}

resource "kubernetes_namespace_v1" "home_ops" {
  metadata {
    name = var.namespace
    labels = {
      # Refuse pods that run as root, allow privilege escalation, or skip seccomp.
      "pod-security.kubernetes.io/enforce" = "restricted"
      "pod-security.kubernetes.io/audit"   = "restricted"
    }
  }
}

# The password lives only in Terraform state and the cluster Secret.
# Git never sees it: the chart refers to the Secret by name.
resource "kubernetes_secret_v1" "postgres" {
  metadata {
    name      = "postgres-credentials"
    namespace = kubernetes_namespace_v1.home_ops.metadata[0].name
  }
  type = "Opaque"
  data = {
    POSTGRES_PASSWORD = var.postgres_password
  }
}

resource "helm_release" "home_ops" {
  name      = "home-ops"
  namespace = kubernetes_namespace_v1.home_ops.metadata[0].name
  chart     = var.chart_path
  wait      = true
  timeout   = 300

  values = [yamlencode({
    telemetry = {
      image = {
        repository = var.telemetry_image_repository
        tag        = var.telemetry_image_tag
      }
      ingress = {
        fromNamespaces = var.ingress_namespaces
        fromPodLabels  = var.ingress_pod_labels
      }
    }
    postgres = {
      existingSecret = kubernetes_secret_v1.postgres.metadata[0].name
      storage = {
        size         = var.postgres_storage_size
        storageClass = var.storage_class
      }
    }
    backup = {
      schedule      = var.backup_schedule
      retentionDays = var.backup_retention_days
      storage = {
        storageClass = var.storage_class
      }
    }
  })]
}
