"""An in-memory stand-in for homeops_ops.kube.Kube. It keeps objects in a dict and follows
JSON merge-patch rules, so the controllers can be tested without a cluster."""

import copy
import uuid


def _merge(target, patch):
    for key, value in patch.items():
        if value is None:
            target.pop(key, None)
        elif isinstance(value, dict) and isinstance(target.get(key), dict):
            _merge(target[key], value)
        else:
            target[key] = copy.deepcopy(value)
    return target


class FakeKube:
    def __init__(self):
        self.store = {}
        self.calls = []

    def _key(self, api_version, kind, namespace, name):
        return (api_version, kind, namespace, name)

    def get(self, api_version, kind, namespace, name):
        obj = self.store.get(self._key(api_version, kind, namespace, name))
        return copy.deepcopy(obj) if obj is not None else None

    def list(self, api_version, kind, namespace, label_selector=None):
        out = []
        for (av, k, ns, _), obj in self.store.items():
            if (av, k, ns) != (api_version, kind, namespace):
                continue
            if label_selector and label_selector not in (obj["metadata"].get("labels") or {}):
                continue
            out.append(copy.deepcopy(obj))
        return out

    def create(self, obj):
        meta = obj["metadata"]
        key = self._key(obj["apiVersion"], obj["kind"], meta["namespace"], meta["name"])
        if key in self.store:
            raise RuntimeError(f"already exists: {key}")
        stored = copy.deepcopy(obj)
        stored["metadata"].setdefault("uid", str(uuid.uuid4()))
        stored["metadata"].setdefault("creationTimestamp", "2026-01-01T00:00:00Z")
        self.store[key] = stored
        self.calls.append(("create", obj["kind"], meta["name"]))

    def patch(self, api_version, kind, namespace, name, body, status=False):
        key = self._key(api_version, kind, namespace, name)
        if key not in self.store:
            raise RuntimeError(f"not found: {key}")
        if status:
            _merge(self.store[key].setdefault("status", {}), body.get("status", {}))
        else:
            _merge(self.store[key], body)
        self.calls.append(("patch", kind, name))

    def delete(self, api_version, kind, namespace, name):
        key = self._key(api_version, kind, namespace, name)
        if key in self.store:
            del self.store[key]
            self.calls.append(("delete", kind, name))

    def remove(self, api_version, kind, namespace, name):
        """Delete an object as if someone ran kubectl delete (no finalizer handling)."""
        self.store.pop(self._key(api_version, kind, namespace, name), None)
