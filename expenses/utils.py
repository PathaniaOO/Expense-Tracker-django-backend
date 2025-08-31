from .models import Account

def get_external_account(user):
    # One hidden account per user, not shown in lists
    acc, _ = Account.objects.get_or_create(
        user=user,
        is_system=True,
        defaults={"name": "External (System)", "balance": 0}
    )
    return acc
