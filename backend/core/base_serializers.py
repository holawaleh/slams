from django.contrib.auth.models import User
from rest_framework import serializers


def _is_tenant_model(model):
    return any(f.name == "org" for f in model._meta.fields)


class TenantSerializer(serializers.ModelSerializer):
    """Base for tenant models.

    Three protections:
      - org is never accepted from input, so it cannot be forged.
      - every relation field only looks up rows in the caller's org, so an
        id from another org gets the same "does not exist" answer as an id
        that was never used. A different message would confirm the row is
        there. Users (lecturer, card holder) are limited to members of the
        org in the same way.
      - as a second line, validate() rejects any related row from another
        org. Subclasses that override validate() must call super().
    """

    def _org(self):
        org = self.context.get("org")
        if org is None:
            raise serializers.ValidationError(
                "Organization context missing.")
        return org

    def get_fields(self):
        fields = super().get_fields()
        org = self.context.get("org")
        if org is None:
            return fields
        for field in fields.values():
            rel = getattr(field, "child_relation", field)
            qs = getattr(rel, "queryset", None)
            if qs is None:
                continue
            if _is_tenant_model(qs.model):
                rel.queryset = qs.filter(org=org)
            elif qs.model is User:
                rel.queryset = qs.filter(memberships__org=org).distinct()
        return fields

    def validate(self, attrs):
        attrs = super().validate(attrs)
        org = self._org()
        for name, value in attrs.items():
            if value is None:
                continue
            related_org = getattr(value, "org_id", None)
            if related_org is not None and related_org != org.id:
                raise serializers.ValidationError(
                    {name: "Not found in your organization."})
        return attrs

    def create(self, validated_data):
        validated_data.pop("org", None)
        validated_data["org"] = self._org()
        return super().create(validated_data)

    def update(self, instance, validated_data):
        validated_data.pop("org", None)   # org can never be reassigned
        return super().update(instance, validated_data)
