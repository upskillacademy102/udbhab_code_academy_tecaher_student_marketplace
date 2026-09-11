"""
Create demo student and teacher accounts you can actually log in as.

WHY THIS EXISTS
    The database had no users beyond the super admin, no teacher profiles and
    no locations, so nothing that reads real data could be looked at: search
    returned nothing, and the Discover page had nothing to discover.

WHAT IT MAKES
    - India -> 8 states -> 12 cities (Teacher cities M2M needs real rows)
    - 8 teachers, each with a Teacher record, a marketplace TeacherProfile,
      subjects / languages / cities, and structured weekly availability
    - 4 students

TWO THINGS THAT MATTER FOR THE TEACHERS TO BE VISIBLE
    1. verification_status must be VERIFIED. With the trust flags off,
       apply_teacher_gate() filters teacher search down to VERIFIED only, so
       a PENDING demo teacher would silently never appear.
    2. TeacherWeeklyAvailability rows must exist. GET /search/teachers/ only
       computes match_percentage from those; without them every result falls
       back to the no-schedule card.

SAFETY
    Idempotent - keyed on email / name, creates only, never updates or
    deletes. Every account is prefixed `demo.` so they are easy to spot and
    easy to remove. Profile photos are left empty on purpose: it is honest to
    the real state of the platform and it exercises the monogram fallback the
    teacher card was designed around.

USAGE
    python manage.py seed_demo
    python manage.py seed_demo --dry-run
"""

from datetime import time

from django.core.management.base import BaseCommand
from django.db import transaction

from apps.accounts.models import User, UserRole
from apps.languages.models import Language
from apps.location.models import City, Country, State
from apps.students.models import EducationLevel, Student
from apps.subjects.models import Subject
from apps.teacher_profile.models import (
    ModerationStatus,
    TeacherProfile,
    TeacherWeeklyAvailability,
    TeachingMode,
    VerificationStatus,
)
from apps.teachers.models import QualificationLevel, Teacher

PASSWORD = "Demo@12345"
TZ = "Asia/Kolkata"

# state name -> (state code, [cities])
LOCATIONS = {
    "Maharashtra": ("MH", ["Mumbai", "Pune"]),
    "Delhi": ("DL", ["New Delhi"]),
    "Karnataka": ("KA", ["Bengaluru"]),
    "Tamil Nadu": ("TN", ["Chennai", "Coimbatore"]),
    "West Bengal": ("WB", ["Kolkata"]),
    "Telangana": ("TG", ["Hyderabad"]),
    "Gujarat": ("GJ", ["Ahmedabad", "Surat"]),
    "Kerala": ("KL", ["Kochi", "Thiruvananthapuram"]),
}

# Availability presets, in the teacher's own local time. The bands here line
# up with the ones the landing page and sign-up offer (morning 06-12,
# afternoon 12-17, evening 17-22) so demo matches score sensibly.
WEEKDAY_EVENING = [(d, time(17, 0), time(21, 0)) for d in (1, 2, 3, 4, 5)]
WEEKDAY_MORNING = [(d, time(7, 0), time(11, 0)) for d in (1, 2, 3, 4, 5)]
TUE_THU_EVENING = [(d, time(18, 0), time(21, 0)) for d in (2, 4)]
WEEKEND_ALLDAY = [(d, time(9, 0), time(18, 0)) for d in (6, 7)]
MON_WED_FRI_AFT = [(d, time(13, 0), time(17, 0)) for d in (1, 3, 5)]
SAT_MORNING = [(6, time(8, 0), time(12, 0))]

TEACHERS = [
    {
        "first": "Priya", "last": "Sharma", "mobile": "9810000101",
        "city": "New Delhi", "state": "Delhi",
        "headline": "Maths that finally makes sense — Class 9 to 12",
        "bio": "Fifteen years teaching board and competitive maths. I work from where you are stuck, not from page one.",
        "experience": 15, "qual": QualificationLevel.MASTERS,
        "qual_detail": "M.Sc. Mathematics, Delhi University",
        "subjects": ["Mathematics", "Test Prep"],
        "languages": ["Hindi", "English"],
        "cities": ["New Delhi"],
        "mode": TeachingMode.BOTH, "rate": "1400.00", "rating": "4.90",
        "availability": TUE_THU_EVENING + SAT_MORNING,
    },
    {
        "first": "Rahul", "last": "Menon", "mobile": "9810000102",
        "city": "Kochi", "state": "Kerala",
        "headline": "Physics for Class 11-12 and JEE, taught slowly",
        "bio": "I teach physics as a story about how things move, not a list of formulas to memorise.",
        "experience": 3, "qual": QualificationLevel.BACHELORS,
        "qual_detail": "B.Tech Mechanical, NIT Calicut",
        "subjects": ["Physics", "Mathematics"],
        "languages": ["Malayalam", "English"],
        "cities": ["Kochi"],
        "mode": TeachingMode.ONLINE, "rate": "950.00", "rating": "0.00",
        "availability": WEEKEND_ALLDAY,
    },
    {
        "first": "Ananya", "last": "Krishnan", "mobile": "9810000103",
        "city": "Chennai", "state": "Tamil Nadu",
        "headline": "Chemistry, Class 9-12 — organic a speciality",
        "bio": "Organic chemistry is patterns, not memorising. Six years getting students to see them.",
        "experience": 6, "qual": QualificationLevel.MASTERS,
        "qual_detail": "M.Sc. Chemistry, University of Madras",
        "subjects": ["Chemistry", "Biology"],
        "languages": ["Tamil", "English"],
        "cities": ["Chennai", "Coimbatore"],
        "mode": TeachingMode.BOTH, "rate": "1100.00", "rating": "4.70",
        "availability": WEEKDAY_EVENING,
    },
    {
        "first": "Meera", "last": "Banerjee", "mobile": "9810000104",
        "city": "Kolkata", "state": "West Bengal",
        "headline": "Accountancy and Economics for Class 11-12 and B.Com",
        "bio": "Ex-auditor. I teach accounts the way it is actually used, then map it back to your syllabus.",
        "experience": 9, "qual": QualificationLevel.PROFESSIONAL_CERTIFICATION,
        "qual_detail": "Chartered Accountant (ICAI)",
        "subjects": ["Accountancy", "Economics"],
        "languages": ["Bengali", "Hindi", "English"],
        "cities": ["Kolkata"],
        "mode": TeachingMode.ONLINE, "rate": "1600.00", "rating": "4.80",
        "availability": MON_WED_FRI_AFT + SAT_MORNING,
    },
    {
        "first": "Arjun", "last": "Patil", "mobile": "9810000105",
        "city": "Pune", "state": "Maharashtra",
        "headline": "Python and Computer Science, beginner to Class 12",
        "bio": "Working developer. We build something small every session, so it sticks.",
        "experience": 5, "qual": QualificationLevel.BACHELORS,
        "qual_detail": "B.E. Computer Engineering, Pune University",
        "subjects": ["Computer Science", "Mathematics"],
        "languages": ["Marathi", "Hindi", "English"],
        "cities": ["Pune", "Mumbai"],
        "mode": TeachingMode.ONLINE, "rate": "1800.00", "rating": "4.60",
        "availability": TUE_THU_EVENING + WEEKEND_ALLDAY,
    },
    {
        "first": "Fatima", "last": "Sheikh", "mobile": "9810000106",
        "city": "Hyderabad", "state": "Telangana",
        "headline": "Spoken English and interview confidence",
        "bio": "For anyone who can read English fine but freezes when they have to speak it. We just talk.",
        "experience": 7, "qual": QualificationLevel.MASTERS,
        "qual_detail": "M.A. English Literature, Osmania University",
        "subjects": ["Spoken English", "English"],
        "languages": ["Urdu", "Telugu", "Hindi", "English"],
        "cities": ["Hyderabad"],
        "mode": TeachingMode.ONLINE, "rate": "800.00", "rating": "4.95",
        "availability": WEEKDAY_MORNING + WEEKDAY_EVENING,
    },
    {
        "first": "Vikram", "last": "Desai", "mobile": "9810000107",
        "city": "Ahmedabad", "state": "Gujarat",
        "headline": "Biology for NEET — 12 years, same syllabus, every year",
        "bio": "I have taught this syllabus long enough to know exactly which twenty marks students lose.",
        "experience": 12, "qual": QualificationLevel.DOCTORATE,
        "qual_detail": "Ph.D. Botany, Gujarat University",
        "subjects": ["Biology", "Test Prep"],
        "languages": ["Gujarati", "Hindi", "English"],
        "cities": ["Ahmedabad", "Surat"],
        "mode": TeachingMode.BOTH, "rate": "2200.00", "rating": "4.85",
        "availability": WEEKDAY_EVENING + WEEKEND_ALLDAY,
    },
    {
        "first": "Sneha", "last": "Rao", "mobile": "9810000108",
        "city": "Bengaluru", "state": "Karnataka",
        "headline": "Hindustani vocal and keyboard, all ages",
        "bio": "Trained in Hindustani classical since I was six. Beginners very welcome — no instrument needed to start.",
        "experience": 1, "qual": QualificationLevel.DIPLOMA,
        "qual_detail": "Sangeet Visharad, Gandharva Mahavidyalaya",
        "subjects": ["Music"],
        "languages": ["Kannada", "Hindi", "English"],
        "cities": ["Bengaluru"],
        "mode": TeachingMode.BOTH, "rate": "400.00", "rating": "0.00",
        "availability": WEEKEND_ALLDAY + MON_WED_FRI_AFT,
    },
]

STUDENTS = [
    {
        "first": "Aarav", "last": "Gupta", "mobile": "9820000201",
        "city": "New Delhi", "state": "Delhi",
        "level": EducationLevel.HIGH_SCHOOL, "grade": "Class 11",
        "subjects": "Mathematics, Physics",
        "bio": "Looking for help with Class 11 maths before the boards.",
    },
    {
        "first": "Ishita", "last": "Nair", "mobile": "9820000202",
        "city": "Kochi", "state": "Kerala",
        "level": EducationLevel.COMPETITIVE_EXAM, "grade": "NEET Aspirant",
        "subjects": "Biology, Chemistry",
        "bio": "NEET next year. Need someone patient for organic chemistry.",
    },
    {
        "first": "Kabir", "last": "Singh", "mobile": "9820000203",
        "city": "Pune", "state": "Maharashtra",
        "level": EducationLevel.UNDERGRADUATE, "grade": "2nd Year B.Com",
        "subjects": "Accountancy, Economics",
        "bio": "Second year B.Com, struggling with cost accounting.",
    },
    {
        "first": "Diya", "last": "Reddy", "mobile": "9820000204",
        "city": "Hyderabad", "state": "Telangana",
        "level": EducationLevel.HOBBY_OTHER, "grade": "Adult learner",
        "subjects": "Spoken English",
        "bio": "Want to speak English confidently at work.",
    },
]


class Command(BaseCommand):
    help = "Create demo students and teachers you can log in as (idempotent)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Report what would be created without writing anything.",
        )

    def handle(self, *args, **options):
        dry = options["dry_run"]
        if dry:
            self.stdout.write(self.style.WARNING("DRY RUN — nothing will be written.\n"))

        missing = self._check_taxonomy()
        if missing:
            self.stdout.write(
                self.style.ERROR(
                    "Taxonomy is missing: %s\nRun `python manage.py seed_taxonomy` first."
                    % ", ".join(missing)
                )
            )
            return

        with transaction.atomic():
            cities = self._seed_locations(dry)
            t_made, t_skip = self._seed_teachers(dry, cities)
            s_made, s_skip = self._seed_students(dry)
            if dry:
                transaction.set_rollback(True)

        self.stdout.write("")
        self.stdout.write(self.style.SUCCESS(f"Teachers: {t_made} created, {t_skip} already present"))
        self.stdout.write(self.style.SUCCESS(f"Students: {s_made} created, {s_skip} already present"))
        if not dry:
            self._print_credentials()

    # ------------------------------------------------------------------
    def _check_taxonomy(self):
        missing = []
        if not Subject.objects.filter(is_active=True).exists():
            missing.append("subjects")
        if not Language.objects.filter(is_active=True).exists():
            missing.append("languages")
        return missing

    def _seed_locations(self, dry):
        """Returns {city_name: City or None}. None only in a dry run."""
        india, created = (None, False)
        if dry:
            india = Country.objects.filter(name="India").first()
        else:
            india, created = Country.objects.get_or_create(
                name="India", defaults={"code": "IN", "is_active": True}
            )
        if created:
            self.stdout.write(self.style.SUCCESS("  + country: India"))

        out = {}
        for state_name, (code, city_names) in LOCATIONS.items():
            state = None
            if not dry:
                state, s_created = State.objects.get_or_create(
                    country=india, name=state_name,
                    defaults={"code": code, "is_active": True},
                )
                if s_created:
                    self.stdout.write(self.style.SUCCESS(f"  + state: {state_name}"))
            for city_name in city_names:
                if dry:
                    out[city_name] = None
                    self.stdout.write(self.style.SUCCESS(f"  + city: {city_name}"))
                    continue
                city, c_created = City.objects.get_or_create(
                    state=state, name=city_name, defaults={"is_active": True}
                )
                out[city_name] = city
                if c_created:
                    self.stdout.write(self.style.SUCCESS(f"  + city: {city_name}"))
        return out

    def _email(self, first, last, role):
        return f"demo.{first.lower()}.{last.lower()}@{role}.udbhab.test"

    def _seed_teachers(self, dry, cities):
        made = skipped = 0
        for t in TEACHERS:
            email = self._email(t["first"], t["last"], "teacher")
            if User.objects.filter(email=email).exists():
                skipped += 1
                self.stdout.write(f"  = teacher exists: {t['first']} {t['last']}")
                continue
            made += 1
            self.stdout.write(self.style.SUCCESS(f"  + teacher: {t['first']} {t['last']} — {t['headline']}"))
            if dry:
                continue

            user = User.objects.create_user(
                email=email, password=PASSWORD, role=UserRole.TEACHER,
                first_name=t["first"], last_name=t["last"],
                mobile=t["mobile"], is_active=True,
            )
            teacher = Teacher.objects.create(
                user=user, bio=t["bio"], experience_years=t["experience"],
                qualification_level=t["qual"], qualification_detail=t["qual_detail"],
                subjects_taught=", ".join(t["subjects"]),
                city=t["city"], state=t["state"], country="India",
            )
            profile = TeacherProfile.objects.create(
                teacher=teacher,
                headline=t["headline"],
                teaching_mode=t["mode"],
                hourly_rate=t["rate"],
                rating=t["rating"],
                # Must be VERIFIED or teacher search hides them entirely —
                # apply_teacher_gate() filters to VERIFIED with trust flags off.
                verification_status=VerificationStatus.VERIFIED,
                moderation_status=ModerationStatus.CLEAR,
            )
            profile.subjects.set(Subject.objects.filter(name__in=t["subjects"]))
            profile.languages.set(Language.objects.filter(name__in=t["languages"]))
            profile.cities.set(
                [cities[c] for c in t["cities"] if cities.get(c) is not None]
            )
            # Structured weekly windows — this is what the matching engine
            # reads to produce a match_percentage.
            for day, start, end in t["availability"]:
                TeacherWeeklyAvailability.objects.get_or_create(
                    teacher_profile=profile, day_of_week=day,
                    start_time=start, end_time=end, timezone=TZ,
                    defaults={"is_active": True},
                )
        return made, skipped

    def _seed_students(self, dry):
        made = skipped = 0
        for s in STUDENTS:
            email = self._email(s["first"], s["last"], "student")
            if User.objects.filter(email=email).exists():
                skipped += 1
                self.stdout.write(f"  = student exists: {s['first']} {s['last']}")
                continue
            made += 1
            self.stdout.write(self.style.SUCCESS(f"  + student: {s['first']} {s['last']} — {s['grade']}"))
            if dry:
                continue

            user = User.objects.create_user(
                email=email, password=PASSWORD, role=UserRole.STUDENT,
                first_name=s["first"], last_name=s["last"],
                mobile=s["mobile"], is_active=True,
            )
            Student.objects.create(
                user=user,
                education_level=s["level"], grade_or_year=s["grade"],
                city=s["city"], state=s["state"], country="India",
                preferred_subjects=s["subjects"], bio=s["bio"],
            )
        return made, skipped

    def _print_credentials(self):
        self.stdout.write("")
        self.stdout.write(self.style.MIGRATE_HEADING("Log in with any of these — password for all: " + PASSWORD))
        self.stdout.write("")
        self.stdout.write("  TEACHERS")
        for t in TEACHERS:
            self.stdout.write(f"    {self._email(t['first'], t['last'], 'teacher')}")
        self.stdout.write("")
        self.stdout.write("  STUDENTS")
        for s in STUDENTS:
            self.stdout.write(f"    {self._email(s['first'], s['last'], 'student')}")
