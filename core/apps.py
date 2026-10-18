from django.apps import AppConfig
from django.db.backends.signals import connection_created

def activate_sqlite_optimizations(sender, connection, **kwargs):
    if connection.vendor == 'sqlite':
        db_name = connection.settings_dict.get('NAME')
        cursor = connection.cursor()
        cursor.execute('PRAGMA foreign_keys = ON;')
        cursor.execute('PRAGMA busy_timeout = 30000;')
        # Only apply WAL to persistent disk-based database files
        if db_name and str(db_name) != ':memory:' and not str(db_name).startswith('file:memory'):
            try:
                cursor.execute('PRAGMA journal_mode = WAL;')
                cursor.execute('PRAGMA synchronous = NORMAL;')
            except Exception:
                pass

class CoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'core'

    def ready(self):
        connection_created.connect(activate_sqlite_optimizations)
