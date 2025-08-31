from django.core.management.base import BaseCommand
from django.contrib.auth import get_user_model
from expenses.models import Category, Account, Expense, Income, Transfer
from decimal import Decimal
import random
from django.utils import timezone
from datetime import timedelta

User = get_user_model()

class Command(BaseCommand):
    help = "Seed the database with sample, realistic data (with random dates)"

    def handle(self, *args, **kwargs):
        # Ensure we have a user
        user = User.objects.first()
        if not user:
            user = User.objects.create_user(username="test", password="test123")

        # Categories
        category_names = ["Food", "Travel", "Rent", "Shopping", "Utilities", "Entertainment", "Health"]
        categories = []
        for name in category_names:
            cat, _ = Category.objects.get_or_create(user=user, name=name)
            categories.append(cat)

        # Accounts
        acc1, _ = Account.objects.get_or_create( user=user, name="SBI Savings", defaults={"balance": Decimal("15000.00")})
        acc2, _ = Account.objects.get_or_create( user=user, name="HDFC Checking", defaults={"balance": Decimal("8000.00")})
        accounts = [acc1, acc2]

        # Incomes (10 random)
        income_sources = ["Salary", "Freelance Project", "Bonus", "Stock Dividend", "Gift from Family"]
        for i in range(10):
            random_days = random.randint(1, 180)  # last 6 months
            Income.objects.create(
                user=user,
                account=random.choice(accounts),
                amount=Decimal(random.randint(10000, 50000)),  # 10k - 50k
                description=random.choice(income_sources),
                created_at=timezone.now() - timedelta(days=random_days),
            )

        # Expenses (30 random)
        expense_items = [
            ("Food", ["Groceries", "Dinner at restaurant", "Snacks"]),
            ("Travel", ["Bus ticket", "Cab fare", "Train pass"]),
            ("Rent", ["Monthly apartment rent"]),
            ("Shopping", ["Clothes", "Shoes", "Electronics"]),
            ("Utilities", ["Electricity bill", "Water bill", "Internet bill"]),
            ("Entertainment", ["Movie ticket", "Concert", "Streaming subscription"]),
            ("Health", ["Doctor visit", "Medicine purchase"]),
        ]

        for i in range(30):
            cat_name, descs = random.choice(expense_items)
            category = Category.objects.filter(user=user, name=cat_name).first()
            random_days = random.randint(1, 180)
            Expense.objects.create(
                user=user,
                account=random.choice(accounts),
                category=category,
                amount=Decimal(random.randint(100, 5000)),  # 100 – 5000
                description=random.choice(descs),
                created_at=timezone.now() - timedelta(days=random_days),
            )

        # Transfers (5 random)
        for i in range(5):
            random_days = random.randint(1, 180)
            Transfer.objects.create(
                user=user,
                from_account=acc1,
                to_account=acc2,
                amount=Decimal(random.randint(500, 3000)),
                created_at=timezone.now() - timedelta(days=random_days),
            )

        self.stdout.write(self.style.SUCCESS("Database seeded with random-dated sample data ✅"))
