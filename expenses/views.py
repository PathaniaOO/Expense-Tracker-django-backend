import random
from calendar import monthrange
from datetime import date, datetime, time
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone
from django.contrib.auth import get_user_model
from django.db.models import Sum, Value, DecimalField
from django.db.models.functions import TruncMonth, Coalesce

from rest_framework import viewsets, permissions, status, generics
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework_simplejwt.exceptions import TokenError

from .models import Expense, Category, Account, Income, Transfer
from .serializers import (
    ExpenseSerializer,
    CategorySerializer,
    AccountSerializer,
    IncomeSerializer,
    TransferSerializer,
    RegisterSerializer,
)
from .utils import get_external_account
from drf_spectacular.utils import (
    extend_schema, extend_schema_view,
    OpenApiParameter, OpenApiExample
)


# ---------------------------------------------------------------------
# Auth views
# ---------------------------------------------------------------------

User = get_user_model()


class RegisterView(generics.CreateAPIView):
    queryset = User.objects.all()
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]

    @extend_schema(tags=["Auth"])
    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = serializer.save()

        refresh = RefreshToken.for_user(user)
        data = {
            "user": {
                "id": user.id,
                "username": user.username,
                "email": user.email,
            },
            "tokens": {
                "access": str(refresh.access_token),
                "refresh": str(refresh),
            },
        }
        headers = self.get_success_headers(serializer.data)
        return Response(data, status=status.HTTP_201_CREATED, headers=headers)


class LogoutView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        request={"application/json": {"type": "object", "properties": {"refresh": {"type": "string"}}}},
        responses={205: None, 400: dict},
        tags=["Auth"],
    )
    def post(self, request):
        refresh_token = request.data.get("refresh")
        if not refresh_token:
            return Response({"detail": "Missing refresh token."}, status=status.HTTP_400_BAD_REQUEST)
        try:
            token = RefreshToken(refresh_token)
            token.blacklist()
            return Response({"detail": "Logout successful"}, status=status.HTTP_205_RESET_CONTENT)
        except TokenError:
            return Response({"detail": "Invalid token"}, status=status.HTTP_400_BAD_REQUEST)


# ---------------------------------------------------------------------
# Base mixin
# ---------------------------------------------------------------------

class OwnedQuerysetMixin:
    def get_queryset(self):
        qs = super().get_queryset()
        return qs.filter(user=self.request.user)

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


# ---------------------------------------------------------------------
# Date helpers (single, canonical set)
# ---------------------------------------------------------------------

def parse_start(s: str) -> date:
    parts = s.split("-")
    y, m = int(parts[0]), int(parts[1])
    d = int(parts[2]) if len(parts) > 2 else 1
    return date(y, m, d)


def parse_end(s: str) -> date:
    parts = s.split("-")
    y, m = int(parts[0]), int(parts[1])
    if len(parts) > 2:
        d = int(parts[2])
    else:
        d = monthrange(y, m)[1]
    return date(y, m, d)


def day_start(dt_date: date):
    dt = datetime.combine(dt_date, time.min)
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


def day_end(dt_date: date):
    dt = datetime.combine(dt_date, time.max)
    if timezone.is_naive(dt):
        return timezone.make_aware(dt, timezone.get_current_timezone())
    return dt


# ---------------------------------------------------------------------
# Category / Account viewsets
# ---------------------------------------------------------------------
@extend_schema_view(
    list=extend_schema(tags=["Categories"]),
    retrieve=extend_schema(tags=["Categories"]),
    create=extend_schema(tags=["Categories"]),
    update=extend_schema(tags=["Categories"]),
    partial_update=extend_schema(tags=["Categories"]),
    destroy=extend_schema(tags=["Categories"]),
)
class CategoryViewSet(OwnedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Category.objects.all()
    serializer_class = CategorySerializer
    permission_classes = [permissions.IsAuthenticated]

@extend_schema_view(
    list=extend_schema(tags=["Accounts"]),
    retrieve=extend_schema(tags=["Accounts"]),
    create=extend_schema(tags=["Accounts"]),
    update=extend_schema(tags=["Accounts"]),
    partial_update=extend_schema(tags=["Accounts"]),
    destroy=extend_schema(tags=["Accounts"]),
)

class AccountViewSet(OwnedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Account.objects.all()
    serializer_class = AccountSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):  # hide system accounts from normal lists
        return super().get_queryset().filter(is_system=False)


# ---------------------------------------------------------------------
# Expense viewset
# ---------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(tags=["Expenses"]),
    retrieve=extend_schema(tags=["Expenses"]),
    create=extend_schema(tags=["Expenses"]),
    update=extend_schema(tags=["Expenses"]),
    partial_update=extend_schema(tags=["Expenses"]),
    destroy=extend_schema(tags=["Expenses"]),
)
class ExpenseViewSet(OwnedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Expense.objects.select_related("account", "category", "user")
    serializer_class = ExpenseSerializer
    permission_classes = [permissions.IsAuthenticated]
    @extend_schema(
        parameters=[
            OpenApiParameter("start", str, OpenApiParameter.QUERY),
            OpenApiParameter("end", str, OpenApiParameter.QUERY),
            OpenApiParameter("account", int, OpenApiParameter.QUERY),
        ],
        responses={200: list[dict]},
        tags=["Expenses"],
    )

    @action(detail=False, methods=["get"])
    def totals_by_category(self, request):
        qs = self.get_queryset()
        start = request.query_params.get("start")
        end = request.query_params.get("end")
        account = request.query_params.get("account")

        if start:
            qs = qs.filter(created_at__gte=day_start(parse_start(start)))
        if end:
            qs = qs.filter(created_at__lte=day_end(parse_end(end)))
        if account is not None:
            try:
                account = int(account)
            except (TypeError, ValueError):
                return Response({"detail": "'account' must be an integer."}, status=400)
            qs = qs.filter(account_id=account)

        data = (
            qs.values("category__id", "category__name")
              .annotate(total=Sum("amount"))
              .order_by("category__name")
        )
        result = [
            {
                "category_id": row["category__id"],
                "category": row["category__name"] or "Uncategorized",
                "total": row["total"] or Decimal("0.00"),
            }
            for row in data
        ]
        return Response(result)
    
    @extend_schema(
        parameters=[
            OpenApiParameter("start", str, OpenApiParameter.QUERY),
            OpenApiParameter("end", str, OpenApiParameter.QUERY),
            OpenApiParameter("account", int, OpenApiParameter.QUERY),
            OpenApiParameter("by", str, OpenApiParameter.QUERY, description="account, category, account_category"),
        ],
        responses={200: list[dict]},
        tags=["Cashflow"],
    )

    @action(detail=False, methods=["get"], url_path="monthly-cashflow")
    def monthly_cashflow(self, request):
        start = request.query_params.get("start")
        end = request.query_params.get("end")
        account = request.query_params.get("account")
        by = request.query_params.get("by")

        exp = self.get_queryset()  # already user-scoped
        inc = Income.objects.filter(user=self.request.user)
        tr_in = Transfer.objects.filter(
            user=self.request.user,
            from_account__is_system=True,  # incoming money to user from external/system
        )

        # Date filters (timezone-aware) + optional account filter applied uniformly
        if start:
            s = day_start(parse_start(start))
            exp = exp.filter(created_at__gte=s)
            inc = inc.filter(created_at__gte=s)
            tr_in = tr_in.filter(created_at__gte=s)
        if end:
            e = day_end(parse_end(end))
            exp = exp.filter(created_at__lte=e)
            inc = inc.filter(created_at__lte=e)
            tr_in = tr_in.filter(created_at__lte=e)
        if account:
            try:
                account_id = int(account)
            except (TypeError, ValueError):
                return Response({"detail": "'account' must be an integer."}, status=400)
            exp = exp.filter(account_id=account_id)
            inc = inc.filter(account_id=account_id)
            tr_in = tr_in.filter(to_account_id=account_id)  # incoming credit goes to this account

        # ---------------- by=account ----------------
        if by == "account":
            exp_rows = (
                exp.annotate(month=TruncMonth("created_at"))
                   .values("month", "account_id", "account__name")
                   .annotate(total=Sum("amount"))
                   .order_by("month", "account__name")
            )
            inc_rows = (
                inc.annotate(month=TruncMonth("created_at"))
                   .values("month", "account_id", "account__name")
                   .annotate(total=Sum("amount"))
                   .order_by("month", "account__name")
            )
            tr_rows = (
                tr_in.annotate(month=TruncMonth("created_at"))
                     .values("month", "to_account_id", "to_account__name")
                     .annotate(total=Sum("amount"))
                     .order_by("month", "to_account__name")
            )

            exp_map = {(r["month"], r["account_id"]): (r["total"] or Decimal("0.00")) for r in exp_rows}
            inc_map = {(r["month"], r["account_id"]): (r["total"] or Decimal("0.00")) for r in inc_rows}

            # Merge incoming transfers (to_account) into income map
            for r in tr_rows:
                key = (r["month"], r["to_account_id"])
                inc_map[key] = inc_map.get(key, Decimal("0.00")) + (r["total"] or Decimal("0.00"))

            months = sorted({m for (m, _) in exp_map.keys()} | {m for (m, _) in inc_map.keys()})
            accounts = {
                **{r["account_id"]: r["account__name"] for r in exp_rows},
                **{r["account_id"]: r["account__name"] for r in inc_rows},
                **{r["to_account_id"]: r["to_account__name"] for r in tr_rows},
            }

            payload = []
            for m in months:
                month_date = m.date() if hasattr(m, "date") else m
                acct_list = []
                month_income = Decimal("0.00")
                month_expense = Decimal("0.00")

                for acc_id, acc_name in accounts.items():
                    inc_total = inc_map.get((m, acc_id), Decimal("0.00"))
                    exp_total = exp_map.get((m, acc_id), Decimal("0.00"))
                    if inc_total or exp_total:
                        acct_list.append({
                            "account_id": acc_id,
                            "account": acc_name,
                            "income": inc_total,
                            "expense": exp_total,
                            "net": inc_total - exp_total,
                        })
                    month_income += inc_total
                    month_expense += exp_total

                payload.append({
                    "month": month_date,
                    "income": month_income,
                    "expense": month_expense,
                    "net": month_income - month_expense,
                    "by_account": acct_list,
                })
            return Response(payload)

        # ---------------- by=category ----------------
        if by == "category":
            exp_rows = (
                exp.annotate(month=TruncMonth("created_at"))
                   .values("month", "category_id", "category__name")
                   .annotate(total=Sum("amount"))
                   .order_by("month", "category__name")
            )
            inc_by_month = (
                inc.annotate(month=TruncMonth("created_at"))
                   .values("month")
                   .annotate(total=Sum("amount"))
                   .order_by("month")
            )
            tr_by_month = (
                tr_in.annotate(month=TruncMonth("created_at"))
                     .values("month")
                     .annotate(total=Sum("amount"))
                     .order_by("month")
            )

            inc_map = {r["month"]: (r["total"] or Decimal("0.00")) for r in inc_by_month}
            for r in tr_by_month:
                m = r["month"]
                inc_map[m] = inc_map.get(m, Decimal("0.00")) + (r["total"] or Decimal("0.00"))

            months = sorted({r["month"] for r in exp_rows} | set(inc_map.keys()))

            per_month = {}
            for r in exp_rows:
                m = r["month"]
                per_month.setdefault(m, []).append({
                    "category_id": r["category_id"],
                    "category": r["category__name"] or "Uncategorized",
                    "total": r["total"] or Decimal("0.00"),
                })

            payload = []
            for m in months:
                month_date = m.date() if hasattr(m, "date") else m
                cats = per_month.get(m, [])
                month_expense = sum((c["total"] for c in cats), Decimal("0.00"))
                month_income = inc_map.get(m, Decimal("0.00"))
                payload.append({
                    "month": month_date,
                    "income": month_income,
                    "expense": month_expense,
                    "net": month_income - month_expense,
                    "by_category": cats,
                })
            return Response(payload)

        # ---------------- by=account_category ----------------
        if by == "account_category":
            exp_rows = (
                exp.annotate(month=TruncMonth("created_at"))
                   .values("month", "account_id", "account__name", "category_id", "category__name")
                   .annotate(total=Sum("amount"))
                   .order_by("month", "account__name", "category__name")
            )
            inc_rows = (
                inc.annotate(month=TruncMonth("created_at"))
                   .values("month", "account_id", "account__name")
                   .annotate(total=Sum("amount"))
                   .order_by("month", "account__name")
            )
            tr_rows = (
                tr_in.annotate(month=TruncMonth("created_at"))
                     .values("month", "to_account_id", "to_account__name")
                     .annotate(total=Sum("amount"))
                     .order_by("month", "to_account__name")
            )

            months = sorted(
                {r["month"] for r in exp_rows}
                | {r["month"] for r in inc_rows}
                | {r["month"] for r in tr_rows}
            )
            per_month = {m: {} for m in months}

            # Seed from incomes
            for r in inc_rows:
                m, acc_id = r["month"], r["account_id"]
                acc_name = r["account__name"]
                per_month[m].setdefault(acc_id, {
                    "account_id": acc_id,
                    "account": acc_name,
                    "income": Decimal("0.00"),
                    "expense": Decimal("0.00"),
                    "by_category": [],
                })
                per_month[m][acc_id]["income"] += r["total"] or Decimal("0.00")

            # Add incoming transfers as income (no category)
            for r in tr_rows:
                m, acc_id = r["month"], r["to_account_id"]
                acc_name = r["to_account__name"]
                per_month[m].setdefault(acc_id, {
                    "account_id": acc_id,
                    "account": acc_name,
                    "income": Decimal("0.00"),
                    "expense": Decimal("0.00"),
                    "by_category": [],
                })
                per_month[m][acc_id]["income"] += r["total"] or Decimal("0.00")

            # Add expenses (with categories)
            for r in exp_rows:
                m, acc_id = r["month"], r["account_id"]
                acc_name = r["account__name"]
                cat_id = r["category_id"]
                cat_name = r["category__name"] or "Uncategorized"
                amt = r["total"] or Decimal("0.00")

                acct = per_month[m].setdefault(acc_id, {
                    "account_id": acc_id,
                    "account": acc_name,
                    "income": Decimal("0.00"),
                    "expense": Decimal("0.00"),
                    "by_category": [],
                })
                acct["expense"] += amt
                acct["by_category"].append({
                    "category_id": cat_id,
                    "category": cat_name,
                    "total": amt,
                })

            payload = []
            for m in months:
                month_date = m.date() if hasattr(m, "date") else m
                accounts_list = []
                month_income = Decimal("0.00")
                month_expense = Decimal("0.00")

                for acc in per_month[m].values():
                    acc_net = acc["income"] - acc["expense"]
                    accounts_list.append({**acc, "net": acc_net})
                    month_income += acc["income"]
                    month_expense += acc["expense"]

                payload.append({
                    "month": month_date,
                    "income": month_income,
                    "expense": month_expense,
                    "net": month_income - month_expense,
                    "by_account": accounts_list,  # each account has by_category[]
                })
            return Response(payload)

        # ---------------- default: month-only totals ----------------
        exp_by_month = (
            exp.annotate(month=TruncMonth("created_at"))
               .values("month")
               .annotate(total=Sum("amount"))
               .order_by("month")
        )
        inc_by_month = (
            inc.annotate(month=TruncMonth("created_at"))
               .values("month")
               .annotate(total=Sum("amount"))
               .order_by("month")
        )
        tr_by_month = (
            tr_in.annotate(month=TruncMonth("created_at"))
                 .values("month")
                 .annotate(total=Sum("amount"))
                 .order_by("month")
        )

        exp_map = {row["month"]: (row["total"] or Decimal("0.00")) for row in exp_by_month}
        inc_map = {row["month"]: (row["total"] or Decimal("0.00")) for row in inc_by_month}
        for r in tr_by_month:
            m = r["month"]
            inc_map[m] = inc_map.get(m, Decimal("0.00")) + (r["total"] or Decimal("0.00"))

        all_months = sorted(set(exp_map.keys()) | set(inc_map.keys()))

        payload = []
        for m in all_months:
            month_date = m.date() if hasattr(m, "date") else m
            income = inc_map.get(m, Decimal("0.00"))
            expense = exp_map.get(m, Decimal("0.00"))
            payload.append({
                "month": month_date,
                "income": income,
                "expense": expense,
                "net": income - expense,
            })
        return Response(payload)


# ---------------------------------------------------------------------
# Income viewset
# ---------------------------------------------------------------------
@extend_schema_view(
    list=extend_schema(tags=["Incomes"]),
    retrieve=extend_schema(tags=["Incomes"]),
    create=extend_schema(tags=["Incomes"]),
    update=extend_schema(tags=["Incomes"]),
    partial_update=extend_schema(tags=["Incomes"]),
    destroy=extend_schema(tags=["Incomes"]),
)

class IncomeViewSet(OwnedQuerysetMixin, viewsets.ModelViewSet):
    queryset = Income.objects.select_related("account", "user")
    serializer_class = IncomeSerializer
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        parameters=[
            OpenApiParameter("start", str, OpenApiParameter.QUERY),
            OpenApiParameter("end", str, OpenApiParameter.QUERY),
            OpenApiParameter("account", int, OpenApiParameter.QUERY),
        ],
        responses={200: dict},
        tags=["Incomes"],
    )

    @action(detail=False, methods=["get"])
    def total(self, request):
        qs = self.get_queryset()
        start = request.query_params.get("start")
        end = request.query_params.get("end")
        account = request.query_params.get("account")

        if start:
            qs = qs.filter(created_at__gte=day_start(parse_start(start)))
        if end:
            qs = qs.filter(created_at__lte=day_end(parse_end(end)))
        if account is not None:
            try:
                account = int(account)
            except (TypeError, ValueError):
                return Response({"detail": "'account' must be an integer."}, status=400)
            qs = qs.filter(account_id=account)

        total_income = qs.aggregate(total=Coalesce(Sum("amount"), Value(Decimal("0.00"), output_field=DecimalField(max_digits=18, decimal_places=2))))["total"]
        return Response({"total": str(total_income)})


# ---------------------------------------------------------------------
# Transfer viewset
# ---------------------------------------------------------------------

@extend_schema_view(
    list=extend_schema(tags=["Transfers"]),
    retrieve=extend_schema(tags=["Transfers"]),
    create=extend_schema(tags=["Transfers"]),
    update=extend_schema(tags=["Transfers"]),
    partial_update=extend_schema(tags=["Transfers"]),
    destroy=extend_schema(tags=["Transfers"]),
)
class TransferViewSet(viewsets.ModelViewSet):
    serializer_class = TransferSerializer
    permission_classes = [permissions.IsAuthenticated]

    def get_queryset(self):
        return (
            Transfer.objects
            .filter(user=self.request.user)
            .select_related("from_account", "to_account")
        )

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)
        
    @extend_schema(
        parameters=[
            OpenApiParameter("start", str, OpenApiParameter.QUERY),
            OpenApiParameter("end", str, OpenApiParameter.QUERY),
            OpenApiParameter("from_account", int, OpenApiParameter.QUERY),
            OpenApiParameter("to_account", int, OpenApiParameter.QUERY),
        ],
        responses={200: dict},
        tags=["Transfers"],
    )

    @action(detail=False, methods=["get"], url_path="total")
    def total(self, request):
        qs = self.get_queryset()
        start = request.query_params.get("start")
        end = request.query_params.get("end")
        from_account = request.query_params.get("from_account")
        to_account = request.query_params.get("to_account")

        # cast ids
        try:
            if from_account is not None:
                from_account = int(from_account)
            if to_account is not None:
                to_account = int(to_account)
        except (TypeError, ValueError):
            return Response(
                {"detail": "'from_account' and 'to_account' must be integers."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # date filters + guard
        try:
            if start and end:
                sdt = day_start(parse_start(start))
                edt = day_end(parse_end(end))
                if sdt > edt:
                    return Response({"detail": "'start' cannot be after 'end'."},
                                    status=status.HTTP_400_BAD_REQUEST)
                qs = qs.filter(created_at__gte=sdt, created_at__lte=edt)
            else:
                if start:
                    qs = qs.filter(created_at__gte=day_start(parse_start(start)))
                if end:
                    qs = qs.filter(created_at__lte=day_end(parse_end(end)))
        except ValueError:
            return Response(
                {"detail": "Invalid 'start'/'end'. Use YYYY-MM-DD or ISO datetime."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if from_account is not None:
            qs = qs.filter(from_account_id=from_account)
        if to_account is not None:
            qs = qs.filter(to_account_id=to_account)

        total = qs.aggregate(
            total=Coalesce(
                Sum("amount"),
                Value(Decimal("0.00"), output_field=DecimalField(max_digits=18, decimal_places=2)),
            )
        )["total"]

        return Response({"total": str(total)})
    
    @extend_schema(
        request={"application/json": {"type": "object", "properties": {
            "account": {"type": "integer"},
            "amount": {"type": "string", "example": "50000.00"},
            "note": {"type": "string", "nullable": True},
        }}},
        responses={201: TransferSerializer},
        tags=["Transfers"],
    )

    @action(detail=False, methods=["post"], url_path="salary")
    def salary(self, request):
        """
        POST /api/transfers/salary/
        {
          "account": <to_account_id>,
          "amount": "10000.00",
          "note": "Aug Salary"   # optional if your Transfer supports it
        }
        """
        user = request.user
        try:
            to_account_id = int(request.data.get("account"))
            amount = Decimal(str(request.data.get("amount")))
        except Exception:
            return Response(
                {"detail": "Provide valid 'account' (id) and 'amount'."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            to_acc = Account.objects.get(pk=to_account_id, user=user, is_system=False)
        except Account.DoesNotExist:
            return Response({"detail": "Account not found."}, status=status.HTTP_404_NOT_FOUND)

        from_acc = get_external_account(user)

        payload = {"from_account": from_acc.pk, "to_account": to_acc.pk, "amount": amount}
        note = request.data.get("note")
        if note is not None:
            payload["note"] = note  # only if your model/serializer has 'note'

        serializer = self.get_serializer(
            data=payload,
            context={**self.get_serializer_context(), "allow_system": True},
        )
        serializer.is_valid(raise_exception=True)
        transfer = serializer.save(user=user)

        return Response(self.get_serializer(transfer).data, status=status.HTTP_201_CREATED)
    
    @extend_schema(
        request={"application/json": {"type": "object", "properties": {
            "account": {"type": "integer"},
            "min": {"type": "string", "example": "40000"},
            "max": {"type": "string", "example": "80000"},
        }}},
        responses={201: TransferSerializer},
        tags=["Transfers"],
    )

    @action(detail=False, methods=["post"], url_path="salary/random")
    def salary_random(self, request):
        """
        POST /api/transfers/salary/random/
        { "account": <id>, "min": "40000", "max": "80000" }
        """
        user = request.user
        try:
            to_account_id = int(request.data.get("account"))
            mn = Decimal(str(request.data.get("min")))
            mx = Decimal(str(request.data.get("max")))
        except Exception:
            return Response({"detail": "Provide valid 'account', 'min', 'max'."},
                            status=status.HTTP_400_BAD_REQUEST)

        if mx < mn:
            return Response({"detail": "'max' must be >= 'min'."},
                            status=status.HTTP_400_BAD_REQUEST)

        try:
            to_acc = Account.objects.get(pk=to_account_id, user=user, is_system=False)
        except Account.DoesNotExist:
            return Response({"detail": "Account not found."}, status=status.HTTP_404_NOT_FOUND)

        from_acc = get_external_account(user)

        # random amount to 2 decimals
        amt = (mn + (mx - mn) * Decimal(random.random())).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        payload = {"from_account": from_acc.pk, "to_account": to_acc.pk, "amount": amt}
        note = request.data.get("note")
        if note is not None:
            payload["note"] = note  # only if your model/serializer has 'note'

        serializer = self.get_serializer(
            data=payload,
            context={**self.get_serializer_context(), "allow_system": True},
        )
        serializer.is_valid(raise_exception=True)
        transfer = serializer.save(user=user)

        return Response(self.get_serializer(transfer).data, status=status.HTTP_201_CREATED)
# ---------------------------------------------------------------------
# Summary (dashboard) endpoint
# ---------------------------------------------------------------------
class SummaryView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    
    @extend_schema(
        parameters=[
            OpenApiParameter("start", str, OpenApiParameter.QUERY),
            OpenApiParameter("end", str, OpenApiParameter.QUERY),
            OpenApiParameter("account", int, OpenApiParameter.QUERY),
        ],
        responses={200: dict},
        tags=["Summary"],
    )

    def get(self, request):
        user = request.user
        start = request.query_params.get("start")
        end = request.query_params.get("end")
        account = request.query_params.get("account")
        
        if not start and not end:
            today = date.today()
            start = f"{today.year:04d}-{today.month:02d}-01"
            last_day = monthrange(today.year, today.month)[1]
            end = f"{today.year:04d}-{today.month:02d}-{last_day:02d}"

        # Base querysets (user-scoped)
        inc = Income.objects.filter(user=user)
        exp = Expense.objects.filter(user=user)
        tr_in = Transfer.objects.filter(user=user, from_account__is_system=True)

        # Filters (same semantics as other endpoints)
        try:
            if start:
                s = day_start(parse_start(start))
                inc = inc.filter(created_at__gte=s)
                exp = exp.filter(created_at__gte=s)
                tr_in = tr_in.filter(created_at__gte=s)
            if end:
                e = day_end(parse_end(end))
                inc = inc.filter(created_at__lte=e)
                exp = exp.filter(created_at__lte=e)
                tr_in = tr_in.filter(created_at__lte=e)
        except ValueError:
            return Response(
                {"detail": "Invalid 'start'/'end'. Use YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if account is not None:
            try:
                account_id = int(account)
            except (TypeError, ValueError):
                return Response({"detail": "'account' must be an integer."}, status=400)
            inc = inc.filter(account_id=account_id)
            exp = exp.filter(account_id=account_id)
            tr_in = tr_in.filter(to_account_id=account_id)  # incoming credit to this account

        # Aggregates (use Coalesce to avoid None)
        inc_total = inc.aggregate(
            total=Coalesce(Sum("amount"), Value(Decimal("0.00"), output_field=DecimalField(max_digits=18, decimal_places=2)))
        )["total"]

        tr_in_total = tr_in.aggregate(
            total=Coalesce(Sum("amount"), Value(Decimal("0.00"), output_field=DecimalField(max_digits=18, decimal_places=2)))
        )["total"]

        exp_total = exp.aggregate(
            total=Coalesce(Sum("amount"), Value(Decimal("0.00"), output_field=DecimalField(max_digits=18, decimal_places=2)))
        )["total"]

        income_incl_transfers = inc_total + tr_in_total
        net = income_incl_transfers - exp_total

        # Current balances (non-system accounts)
        accounts_qs = (
            Account.objects.filter(user=user, is_system=False)
            .values("id", "name", "balance")
            .order_by("name")
        )
        by_account = [
            {"account_id": row["id"], "account": row["name"], "balance": str(row["balance"])}
            for row in accounts_qs
        ]
        total_balance = sum((Decimal(str(a["balance"])) for a in by_account), Decimal("0.00"))

        # Response
        payload = {
            "period": {
                "start": start or None,
                "end": end or None,
                "account": int(account) if account is not None else None,
            },
            "totals": {
                "income": str(inc_total),
                "transfers_in": str(tr_in_total),
                "income_including_transfers": str(income_incl_transfers),
                "expense": str(exp_total),
                "net": str(net),
            },
            "balances": {
                "total_balance": str(total_balance),
                "by_account": by_account,
            },
        }
        return Response(payload, status=200)
