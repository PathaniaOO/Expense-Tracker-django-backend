from django.contrib.auth.models import AbstractUser
from django.db import models, transaction
from django.db.models import F, Q
from django.core.exceptions import ValidationError
from decimal import Decimal

# Create your models here.

class User(AbstractUser):
  pass

class Category(models.Model):
  name=models.CharField(max_length=64)
  user=models.ForeignKey(User,on_delete=models.CASCADE,related_name='categories')
  created_at=models.DateTimeField(auto_now_add=True)
  updated_at=models.DateTimeField(auto_now=True)
  
  class Meta:
    constraints = [
      models.UniqueConstraint(fields=['user', 'name'], name='unique_category_name_per_user')
    ]

  def __str__(self):
    return self.name
  
class Account(models.Model):
  user = models.ForeignKey(User, on_delete=models.CASCADE,related_name='accounts')
  name = models.CharField(max_length=64)
  balance = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("0.00"))
  is_system = models.BooleanField(default=False)
  
  class Meta:
    constraints = [
      models.UniqueConstraint(fields=['user', 'name'], name='unique_account_name_per_user')
    ]

  def __str__(self):
    label = " (hidden)" if self.is_system else ""
    return f"{self.name}{label}"
  
  
class Expense(models.Model):
  user = models.ForeignKey(User, on_delete=models.CASCADE,related_name='expenses')
  account = models.ForeignKey(Account, on_delete=models.PROTECT,related_name='expenses')
  category = models.ForeignKey(Category, on_delete=models.PROTECT,related_name='expenses')
  amount = models.DecimalField(max_digits=10, decimal_places=2)
  description = models.TextField()
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)
  
  class Meta:
        constraints = [
            models.CheckConstraint(check=Q(amount__gt=0), name='expense_amount_gt_0'),
        ]

  def __str__(self):
    return f"{self.amount} - {self.description}"
  
  def clean(self):
        if self.account_id and self.account.user_id != self.user_id:
            raise ValidationError({'account': 'Account must belong to the same user.'})
        if self.category_id and self.category.user_id != self.user_id:
            raise ValidationError({'category': 'Category must belong to the same user.'})
        if getattr(self.account, "is_system", False):
            raise ValidationError({'account': 'System account cannot be used for expenses.'})

  def save(self,*args,**kwargs):
    self.full_clean()
    with transaction.atomic():
      if self.pk:
        prev=Expense.objects.select_related("account").get(pk=self.pk)
        if prev.account_id != self.account_id:
          Account.objects.filter(pk=prev.account_id).update(balance=F('balance') + prev.amount)
          Account.objects.filter(pk=self.account_id).update(balance=F('balance') - self.amount)
        else:
          delta=self.amount - prev.amount
          Account.objects.filter(pk=self.account_id).update(balance=F('balance') - delta)
      else:
        Account.objects.filter(pk=self.account_id).update(balance=F("balance")-self.amount)
      super().save(*args,**kwargs)
      
  def delete(self,*args,**kwargs):
    with transaction.atomic():
      Account.objects.filter(pk=self.account_id).update(balance=F("balance")+self.amount)
      super().delete(*args,**kwargs)

class Income(models.Model):
  user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='incomes')
  account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='incomes')
  amount = models.DecimalField(max_digits=10, decimal_places=2)
  description = models.TextField()
  created_at = models.DateTimeField(auto_now_add=True)
  updated_at = models.DateTimeField(auto_now=True)
  
  class Meta:
        constraints = [
            models.CheckConstraint(check=Q(amount__gt=0), name='income_amount_gt_0'),
        ]

  def __str__(self):
    return f"{self.amount} - {self.description}"
  
  def clean(self):
        if self.account_id and self.account.user_id != self.user_id:
            raise ValidationError({'account': 'Account must belong to the same user.'})
        if getattr(self.account, "is_system", False):
            raise ValidationError({'account': 'System account cannot be used for incomes.'})

  def save(self, *args, **kwargs):
    self.full_clean()
    with transaction.atomic():
      if self.pk:
        prev = Income.objects.select_related("account").get(pk=self.pk)
        if prev.account_id != self.account_id:
          Account.objects.filter(pk=prev.account_id).update(balance=F('balance') - prev.amount)
          Account.objects.filter(pk=self.account_id).update(balance=F('balance') + self.amount)
        else:
          delta = self.amount - prev.amount
          Account.objects.filter(pk=self.account_id).update(balance=F('balance') + delta)
      else:
        Account.objects.filter(pk=self.account_id).update(balance=F("balance") + self.amount)
      super().save(*args, **kwargs)

  def delete(self, *args, **kwargs):
    with transaction.atomic():
      Account.objects.filter(pk=self.account_id).update(balance=F("balance") - self.amount)
      super().delete(*args, **kwargs)

class Transfer(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='transfers')
    from_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='transfers_from')
    to_account = models.ForeignKey(Account, on_delete=models.PROTECT, related_name='transfers_to')
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.CheckConstraint(check=Q(amount__gt=0), name='transfer_amount_gt_0'),
            models.CheckConstraint(check=~Q(from_account=F('to_account')), name='transfer_from_to_different'),
        ]

    def __str__(self):
        return f"Transfer {self.amount} from {self.from_account} to {self.to_account}"

    def clean(self):
        if self.amount is None or self.amount <= 0:
            raise ValidationError({'amount': 'Amount must be > 0.'})
        if self.from_account_id == self.to_account_id:
            raise ValidationError('from_account and to_account must be different.')
        # Optional: enforce ownership in app layer too
        if self.from_account.user_id != self.user_id:
            raise ValidationError({'from_account': 'Account must belong to the same user.'})
        if self.to_account.user_id != self.user_id:
            raise ValidationError({'to_account': 'Account must belong to the same user.'})

    def _reverse_effect(self, prev):
        Account.objects.filter(pk=prev.from_account_id).update(balance=F('balance') + prev.amount)
        Account.objects.filter(pk=prev.to_account_id).update(balance=F('balance') - prev.amount)

    def _apply_effect(self):
        Account.objects.filter(pk=self.from_account_id).update(balance=F('balance') - self.amount)
        Account.objects.filter(pk=self.to_account_id).update(balance=F('balance') + self.amount)

    def save(self, *args, **kwargs):
        # Safe pattern: lock -> reverse previous (if updating) -> validate funds -> apply -> save
        self.full_clean()

        with transaction.atomic():
            # Lock both accounts so concurrent transfers can’t interleave
            locked = list(Account.objects.select_for_update().filter(
                pk__in=[self.from_account_id, self.to_account_id]
            ))
            if len(locked) != 2:
                raise ValidationError("Both accounts must exist.")

            if self.pk:
                prev = Transfer.objects.select_related('from_account', 'to_account').get(pk=self.pk)
                # Always reverse previous effect completely
                self._reverse_effect(prev)

            # Optional overdraft check (remove if you allow negatives)
            from_acct = Account.objects.select_for_update().get(pk=self.from_account_id)
            allow_overdraft = getattr(from_acct, "is_system", False)

            if not allow_overdraft and from_acct.balance < self.amount:
                # If this was an update, we already reversed – put it back so system stays unchanged
                if self.pk:
                    Account.objects.filter(pk=prev.from_account_id).update(balance=F('balance') - prev.amount)
                    Account.objects.filter(pk=prev.to_account_id).update(balance=F('balance') + prev.amount)
                raise ValidationError({'amount': 'Insufficient funds in from_account.'})

            # Apply current effect and save row
            self._apply_effect()
            super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            prev = Transfer.objects.get(pk=self.pk)
            self._reverse_effect(prev)
            super().delete(*args, **kwargs)