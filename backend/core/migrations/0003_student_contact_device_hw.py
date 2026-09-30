from django.db import migrations, models


def join_names(apps, schema_editor):
    """Carry every existing student's name into the single full_name
    field before first_name and last_name are dropped."""
    Student = apps.get_model("core", "Student")
    for s in Student.objects.all().only("id", "first_name", "last_name"):
        s.full_name = " ".join(p for p in (s.first_name, s.last_name) if p)
        s.save(update_fields=["full_name"])


def split_names(apps, schema_editor):
    Student = apps.get_model("core", "Student")
    for s in Student.objects.all().only("id", "full_name"):
        first, _, last = s.full_name.partition(" ")
        s.first_name, s.last_name = first, last
        s.save(update_fields=["first_name", "last_name"])


class Migration(migrations.Migration):

    dependencies = [
        ("core", "0002_tap_device_outcome"),
    ]

    operations = [
        migrations.AddField(
            model_name="student", name="full_name",
            field=models.CharField(max_length=128, default=""),
            preserve_default=False),
        migrations.AddField(
            model_name="student", name="phone",
            field=models.CharField(max_length=20, blank=True)),
        migrations.AddField(
            model_name="student", name="email",
            field=models.EmailField(max_length=254, blank=True)),
        migrations.RunPython(join_names, split_names),
        migrations.RemoveField(model_name="student", name="first_name"),
        migrations.RemoveField(model_name="student", name="last_name"),

        migrations.AlterField(
            model_name="student", name="short_name",
            field=models.CharField(max_length=16, blank=True,
                                   help_text="Shown on the reader's display")),
        migrations.AlterField(
            model_name="student", name="matric_no",
            field=models.CharField(max_length=32, blank=True)),
        migrations.RemoveConstraint(
            model_name="student", name="uniq_matric_per_org"),
        migrations.AddConstraint(
            model_name="student",
            constraint=models.UniqueConstraint(
                fields=("org", "matric_no"),
                condition=~models.Q(matric_no=""),
                name="uniq_matric_per_org")),
        migrations.AddIndex(
            model_name="student",
            index=models.Index(fields=["org", "level"],
                               name="core_studen_org_id_762387_idx")),

        migrations.AddField(
            model_name="device", name="hardware_id",
            field=models.CharField(max_length=17, unique=True, null=True,
                                   blank=True)),
    ]
