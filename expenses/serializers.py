from rest_framework import serializers
from .models import User,Category,Account,Expense,Income,Transfer

class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ['id', 'username', 'email']
        
class RegisterSerializer(serializers.ModelSerializer):
    password = serializers.CharField(write_only=True, min_length=8)

    class Meta:
        model = User
        fields = ["id", "username", "email", "password"]

    def validate_username(self, value):
        if User.objects.filter(username=value).exists():
            raise serializers.ValidationError("Username is already taken.")
        return value

    def validate_email(self, value):
        if value and User.objects.filter(email=value).exists():
            raise serializers.ValidationError("Email is already in use.")
        return value

    def create(self, validated_data):
        # Use create_user so the password is hashed
        return User.objects.create_user(
            username=validated_data["username"],
            email=validated_data.get("email"),
            password=validated_data["password"],
        )

class CategorySerializer(serializers.ModelSerializer):
    class Meta:
        model = Category
        fields = ['id', 'name']

class AccountSerializer(serializers.ModelSerializer):
    class Meta:
        model = Account
        fields = ['id', 'name', 'balance']
        read_only_fields = ['balance']

class ExpenseSerializer(serializers.ModelSerializer):
    class Meta:
        model = Expense
        fields = ['id', 'account', 'category', 'amount', 'description', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, attrs):
        user=self.context['request'].user
        account=attrs.get('account') or getattr(self.instance,'account',None)
        category=attrs.get('category') or getattr(self.instance,'category',None)
        amount=attrs.get('amount') or getattr(self.instance,'amount',None)

        if account and account.user_id != user.id:
            raise serializers.ValidationError({'account': 'Account must belong to the user.'})
        if category and category.user_id != user.id:
            raise serializers.ValidationError({'category': 'Category must belong to the user.'})
        if amount is None or amount <= 0:
            raise serializers.ValidationError({'amount': 'Amount must be positive.'})

        return attrs

class IncomeSerializer(serializers.ModelSerializer):
    class Meta:
        model = Income
        fields = ['id', 'account', 'amount', 'description', 'created_at', 'updated_at']
        read_only_fields = ['id', 'created_at', 'updated_at']

    def validate(self, attrs):
        user = self.context['request'].user
        account = attrs.get('account') or getattr(self.instance, 'account', None)
        amount = attrs.get('amount') or getattr(self.instance, 'amount', None)

        if amount is None or amount <= 0:
            raise serializers.ValidationError({'amount': 'Amount must be > 0.'})
        if account and account.user_id != user.id:
            raise serializers.ValidationError({'account': 'Account must belong to the user.'})
        return attrs


class TransferSerializer(serializers.ModelSerializer):
    class Meta:
        model = Transfer
        fields = ['id', 'from_account', 'to_account', 'amount', 'created_at']
        read_only_fields = ['id', 'created_at']

    def validate(self, attrs):
        user = self.context['request'].user

        # Support PATCH: fall back to instance values when a field isn't provided
        from_account = attrs.get('from_account', getattr(self.instance, 'from_account', None))
        to_account   = attrs.get('to_account',   getattr(self.instance, 'to_account',   None))
        amount       = attrs.get('amount',       getattr(self.instance, 'amount',       None))

        # On CREATE, all three must be present
        if self.instance is None:
            missing = [name for name, val in [('from_account', from_account),
                                              ('to_account', to_account),
                                              ('amount', amount)] if val is None]
            if missing:
                raise serializers.ValidationError({m: 'This field is required.' for m in missing})

        # Amount must be > 0
        if amount is None or amount <= 0:
            raise serializers.ValidationError({'amount': 'Amount must be greater than 0.'})

        # Accounts must be different (only if both are known)
        if from_account and to_account and from_account.pk == to_account.pk:
            raise serializers.ValidationError('from_account and to_account must be different.')

        # Ownership checks (when provided)
        if from_account and from_account.user_id != user.id:
            raise serializers.ValidationError({'from_account': 'Account does not belong to you.'})
        if to_account and to_account.user_id != user.id:
            raise serializers.ValidationError({'to_account': 'Account does not belong to you.'})

        # Disallow system accounts for normal transfers (guard Nones!)
        allow_system = self.context.get('allow_system', False)
        if (from_account and from_account.is_system or to_account and to_account.is_system) and not allow_system:
            raise serializers.ValidationError('System accounts cannot be used in regular transfers.')

        return attrs