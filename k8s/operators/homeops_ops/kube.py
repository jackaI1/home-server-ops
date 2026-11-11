"""A thin wrapper over the kubernetes client. The controllers work on plain dicts through this class,
so their logic can be tested against an in-memory fake with the same methods."""

from kubernetes.dynamic.exceptions import NotFoundError


def _plain(obj):
    return obj.to_dict() if hasattr(obj, "to_dict") else dict(obj)


class Kube:
    def __init__(self, dyn=None):
        if dyn is None:
            from kubernetes import client, config, dynamic
            try:
                config.load_incluster_config()
            except config.ConfigException:
                config.load_kube_config()
            dyn = dynamic.DynamicClient(client.ApiClient())
        self.dyn = dyn

    def _res(self, api_version, kind):
        return self.dyn.resources.get(api_version=api_version, kind=kind)

    def get(self, api_version, kind, namespace, name):
        try:
            return _plain(self._res(api_version, kind).get(name=name, namespace=namespace))
        except NotFoundError:
            return None

    def list(self, api_version, kind, namespace, label_selector=None):
        kwargs = {"namespace": namespace}
        if label_selector:
            kwargs["label_selector"] = label_selector
        return [_plain(item) for item in self._res(api_version, kind).get(**kwargs).items]

    def create(self, obj):
        self._res(obj["apiVersion"], obj["kind"]).create(body=obj, namespace=obj["metadata"]["namespace"])

    def patch(self, api_version, kind, namespace, name, body, status=False):
        """JSON merge patch. With status=True it patches the status subresource."""
        res = self._res(api_version, kind)
        if status:
            res = res.status
        res.patch(body=body, name=name, namespace=namespace, content_type="application/merge-patch+json")

    def delete(self, api_version, kind, namespace, name):
        try:
            self._res(api_version, kind).delete(name=name, namespace=namespace)
        except NotFoundError:
            pass
