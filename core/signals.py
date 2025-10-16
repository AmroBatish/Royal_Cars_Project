from django.db.models.signals import post_migrate
from django.dispatch import receiver
from django.contrib.auth import get_user_model

@receiver(post_migrate)
def create_default_admin(sender, **kwargs):
    User = get_user_model()
    if sender.label == "core":  
        if not User.objects.filter(username="admin").exists():
            User.objects.create_superuser(
                username="admin",
                email="admin@example.com",
                password="admin",
                role="admin"
            )
            print("✅ Default admin created (username=admin, password=admin)")