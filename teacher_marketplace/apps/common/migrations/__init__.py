"""
Notes on choices:
Empty, but necessary: Django's makemigrations/migrate commands scan each installed app for a migrations package. Without this __init__.py, Django would either error or silently skip checking this app for migrations — better to have the folder correctly recognized as empty-by-design than missing entirely.
No migration files will ever be generated here as long as UUIDModel, TimestampModel, SoftDeleteModel, AuditModel, and BaseModel all keep Meta.abstract = True — abstract models never create their own database table or migration. This folder exists purely so the app structure is complete and consistent with every other app (accounts, students, teachers), all of which will have real migrations.
"""
