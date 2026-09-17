"""
Lead visibility gating for the lead_engine app.

BUG THIS FIXES: apps.lead_engine.services.lead_generation_service.
generate_leads_for_requirement() creates a soft Lead row for every
eligible candidate teacher up front (Phase 2's ranking/scoring
pipeline needs that to exist so LeadMatchDetailView/ranking tests
keep working) - but nothing downstream of that ever re-checked
whether a given teacher currently holds an actual offer for it.
apps.matching.services.lead_distribution_service.LeadDistributionService
builds the real tiered/nearest-first cascade via LeadAssignment rows,
but until now LeadListView/LeadDetailView/UnlockLeadView read Lead
rows directly - so every eligible teacher could see and unlock a
lead immediately, regardless of whose turn it actually was. That is
the literal "every teacher sees the offline requirement no matter
the distance" bug.

leads_visible_to() is the single choke point all three views must
read through instead of a bare Lead.objects.filter(teacher_profile=...).
A Lead is visible to a teacher if EITHER:
    - they already unlocked it (contact_unlocked=True) - unlocked
      leads stay visible forever, regardless of what happens to the
      underlying LeadAssignment afterward (matches PendingRatingsView/
      LeadExportView, which already filter on contact_unlocked alone);
    - OR they currently hold a live LeadAssignment for it: never_expires
      (a direct offer - always visible, that's the point of it never
      expiring), or still open (ASSIGNED/VIEWED) and not yet expired,
      or ACCEPTED (a teacher who claimed first refusal via the Offers
      flow should see it here even before spending an unlock).

IMPORTANT WRINKLE: LeadDistributionService.distribute_lead() is only
ever handed ONE "canonical" Lead per requirement (see
apps.lead_engine.tasks.process_requirement_leads) and every
LeadAssignment it creates for that requirement - for EVERY offered
teacher, not just the canonical one - points its `lead` FK at that
SAME canonical Lead row. So a non-canonical teacher's OWN Lead row
(the one `Lead.objects.filter(teacher_profile=that_teacher)` returns)
never shares a primary key with any LeadAssignment.lead_id, even
though that teacher genuinely holds an assignment for the SAME
underlying student_requirement. Matching on
`lead__student_requirement_id` instead of `lead_id` is what makes
this work for every offered teacher, not just the canonical one -
matching on the literal Lead pk would silently 404 everyone else.
"""

from django.db.models import Exists, OuterRef, Q
from django.utils import timezone

from apps.lead_engine.models import Lead, LeadStatus


def leads_visible_to(teacher_profile):
    """QuerySet[Lead] - every lead this teacher is currently allowed
    to see (and therefore act on: view, unlock)."""
    from apps.matching.models import AssignmentStatus, LeadAssignment

    now = timezone.now()
    live_assignment = LeadAssignment.objects.filter(
        lead__student_requirement_id=OuterRef("student_requirement_id"),
        teacher=teacher_profile.teacher,
    ).filter(
        Q(never_expires=True)
        | Q(status=AssignmentStatus.ACCEPTED)
        | Q(
            status__in=[AssignmentStatus.ASSIGNED, AssignmentStatus.VIEWED],
            expires_at__gt=now,
        )
    )
    return (
        Lead.objects.filter(teacher_profile=teacher_profile)
        .exclude(status=LeadStatus.REJECTED)
        .filter(Q(contact_unlocked=True) | Q(Exists(live_assignment)))
    )
