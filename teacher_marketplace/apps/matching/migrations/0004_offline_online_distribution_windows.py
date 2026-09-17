import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("matching", "0003_alter_languagealias_alias_text_and_more"),
    ]

    operations = [
        # Rename (not remove+add) so any admin-configured value survives -
        # the field keeps its exact meaning for offline/both, it's just
        # named for what it now exclusively governs now that online has
        # its own separate windows below.
        migrations.RenameField(
            model_name="matchingconfig",
            old_name="lead_response_window_hours",
            new_name="offline_response_window_hours",
        ),
        migrations.AlterField(
            model_name="matchingconfig",
            name="offline_response_window_hours",
            field=models.PositiveSmallIntegerField(
                default=24,
                help_text=(
                    "How long an offline/both lead stays offered to one "
                    "teacher (or a tied group at the same distance) before "
                    "cascading to the next-nearest untried teacher."
                ),
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(720),
                ],
                verbose_name="offline response window (hours)",
            ),
        ),
        migrations.AddField(
            model_name="matchingconfig",
            name="online_tier_window_hours",
            field=models.PositiveSmallIntegerField(
                default=8,
                help_text=(
                    "How long each subscription tier gets before an online "
                    "lead reveals to the next tier down - on a fixed clock, "
                    "independent of whether anyone in an earlier tier "
                    "unlocked it."
                ),
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(720),
                ],
                verbose_name="online tier window (hours)",
            ),
        ),
        migrations.AddField(
            model_name="matchingconfig",
            name="lead_visibility_window_hours",
            field=models.PositiveSmallIntegerField(
                default=24,
                help_text=(
                    "How long an online lead stays visible to one teacher, "
                    "counted from when it was first shown to them - "
                    "separate from the tier-reveal clock above."
                ),
                validators=[
                    django.core.validators.MinValueValidator(1),
                    django.core.validators.MaxValueValidator(720),
                ],
                verbose_name="lead visibility window (hours)",
            ),
        ),
        migrations.AddField(
            model_name="leadassignment",
            name="is_direct",
            field=models.BooleanField(
                db_index=True,
                default=False,
                help_text=(
                    "True only for a student's direct 'Learn with this "
                    "teacher' offer - never part of the general "
                    "subscription/distance cascade, and excluded from the "
                    "teacher's ordinary Leads list."
                ),
                verbose_name="is direct offer",
            ),
        ),
        migrations.AddField(
            model_name="leadassignment",
            name="never_expires",
            field=models.BooleanField(
                default=False,
                help_text=(
                    "True for a direct offer: no response window, so the "
                    "expiry sweep skips it entirely."
                ),
                verbose_name="never expires",
            ),
        ),
        migrations.RemoveIndex(
            model_name="leadassignment",
            name="idx_assignment_expiry_scan",
        ),
        migrations.AddIndex(
            model_name="leadassignment",
            index=models.Index(
                fields=["status", "never_expires", "expires_at"],
                name="idx_assignment_expiry_scan",
            ),
        ),
        migrations.RemoveConstraint(
            model_name="matchingconfig",
            name="matching_config_sane_ranges",
        ),
        migrations.AddConstraint(
            model_name="matchingconfig",
            constraint=models.CheckConstraint(
                check=models.Q(
                    ("subject_match_threshold__lte", 100),
                    ("language_match_threshold__lte", 100),
                    ("time_match_threshold_minutes__gte", 1),
                    ("time_match_threshold_minutes__lte", 1440),
                    ("initial_location_radius_km__gte", 1),
                    ("initial_location_radius_km__lte", 5000),
                    ("location_radius_increment_km__gte", 1),
                    ("location_radius_increment_km__lte", 5000),
                    ("max_location_radius_km__gte", 1),
                    ("max_location_radius_km__lte", 5000),
                    ("offline_response_window_hours__gte", 1),
                    ("offline_response_window_hours__lte", 720),
                    ("online_tier_window_hours__gte", 1),
                    ("online_tier_window_hours__lte", 720),
                    ("lead_visibility_window_hours__gte", 1),
                    ("lead_visibility_window_hours__lte", 720),
                    (
                        "initial_location_radius_km__lte",
                        models.F("max_location_radius_km"),
                    ),
                ),
                name="matching_config_sane_ranges",
            ),
        ),
    ]
