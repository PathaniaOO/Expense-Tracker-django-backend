from django.urls import path,include
from rest_framework.routers import DefaultRouter
from .views import ExpenseViewSet, CategoryViewSet, AccountViewSet, IncomeViewSet,TransferViewSet,SummaryView

router = DefaultRouter()
router.register(r'expenses', ExpenseViewSet,basename='expense')
router.register(r'categories', CategoryViewSet,basename='category')
router.register(r'accounts', AccountViewSet,basename='account')
router.register(r'incomes', IncomeViewSet, basename='income')
router.register(r'transfers', TransferViewSet, basename='transfer')

urlpatterns = [
    path('', include(router.urls)),
    path('summary/', SummaryView.as_view(), name='summary'),
]