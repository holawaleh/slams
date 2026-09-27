from rest_framework import serializers


class TenantSerializer(serializers.ModelSerializer):
    """Base for tenant models.

    Two protections:
      - org is never accepted from input, so it cannot be forged.
      - every relation the caller submits is checked to belong to the
        same org, so nobody can attach their row to someone else's data.
    """

    def _org(self):
        org = self.context.get("org")
        if org is None:
            raise serializers.ValidationError(
                "Organization context missing.")
        return org

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
