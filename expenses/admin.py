from django.contrib import admin
from .models import User, Category, Account, Expense

# Register your models here.

@admin.register(User)
class UserAdmin(admin.ModelAdmin):
    pass

@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display=('id', 'name','user','created_at','updated_at')
    list_filter=('user',)
    search_fields=('name',)

@admin.register(Account)
class AccountAdmin(admin.ModelAdmin):
    list_display=('id', 'name','user','balance')
    list_filter=('user',)
    search_fields=('name',)

@admin.register(Expense)
class ExpenseAdmin(admin.ModelAdmin):
    list_display=("id", "amount", "description", "user", "account", "category", "created_at")
    list_filter=('user', 'account', 'category')
    search_fields=('description',)
  