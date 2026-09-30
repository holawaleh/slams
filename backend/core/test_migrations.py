from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase


class JoinNamesMigrationTest(TransactionTestCase):
    """0003 folds first_name + last_name into full_name. Existing students
    in a live database must come through with their names intact."""

    before = [("core", "0002_tap_device_outcome")]
    after = [("core", "0003_student_contact_device_hw")]

    def test_names_are_joined(self):
        executor = MigrationExecutor(connection)
        executor.migrate(self.before)
        old = executor.loader.project_state(self.before).apps
        Org = old.get_model("core", "Organization")
        Student = old.get_model("core", "Student")
        org = Org.objects.create(name="U", slug="u")
        Student.objects.create(org=org, matric_no="M1", first_name="Ada",
                               last_name="Obi", short_name="OBI A.")
        Student.objects.create(org=org, matric_no="M2", first_name="Solo",
                               last_name="")

        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(self.after)
        new = executor.loader.project_state(self.after).apps
        names = dict(new.get_model("core", "Student").objects
                     .values_list("matric_no", "full_name"))
        self.assertEqual(names, {"M1": "Ada Obi", "M2": "Solo"})

        # Leave the schema as the rest of the suite expects it.
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
