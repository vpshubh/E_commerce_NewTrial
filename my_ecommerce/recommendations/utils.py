from django.db.models import Count, Q, F, ExpressionWrapper, FloatField
from django.db.models.functions import Coalesce
from django.utils import timezone
import datetime
from products.models import Product, Category
from orders.models import OrderItem
from reviews.models import Review
import random


def get_recently_viewed_products(request, limit=6):
    """
    Get recently viewed products for a user

    Args:
        request: HTTP request object
        limit: Maximum number of products to return

    Returns:
        QuerySet of recently viewed products
    """
    # Get recently viewed product IDs from session
    viewed_products = request.session.get('viewed_products', [])

    # Reverse the list to get most recent first
    viewed_products.reverse()

    # Get the products
    products = []
    for product_id in viewed_products[:limit]:
        try:
            product = Product.objects.get(id=product_id, is_active=True)
            products.append(product)
        except Product.DoesNotExist:
            pass

    return products


def add_product_to_recently_viewed(request, product):
    """
    Add a product to the user's recently viewed products

    Args:
        request: HTTP request object
        product: Product object or ID
    """
    if isinstance(product, Product):
        product_id = product.id
    else:
        product_id = product

    # Get current list from session
    viewed_products = request.session.get('viewed_products', [])

    # Remove if already in list
    if product_id in viewed_products:
        viewed_products.remove(product_id)

    # Add to the end of the list
    viewed_products.append(product_id)

    # Keep only the last 30 products
    viewed_products = viewed_products[-30:]

    # Save back to session
    request.session['viewed_products'] = viewed_products


def get_frequently_bought_together(product, limit=4):
    """
    Get products that are frequently bought together with the given product

    Args:
        product: Product object
        limit: Maximum number of products to return

    Returns:
        QuerySet of products frequently bought with the given product
    """
    # Get orders containing the product
    orders_with_product = OrderItem.objects.filter(
        product_variant__product=product
    ).values_list('order_id', flat=True)

    # Get products from these orders, excluding the current product
    product_ids = OrderItem.objects.filter(
        order_id__in=orders_with_product
    ).exclude(
        product_variant__product=product
    ).values_list(
        'product_variant__product', flat=True
    )

    # Count occurrences of each product
    product_counts = {}
    for pid in product_ids:
        product_counts[pid] = product_counts.get(pid, 0) + 1

    # Sort by count, highest first
    sorted_products = sorted(product_counts.items(), key=lambda x: x[1], reverse=True)

    # Get top products
    top_product_ids = [p[0] for p in sorted_products[:limit]]

    # Get product objects
    if top_product_ids:
        return Product.objects.filter(id__in=top_product_ids, is_active=True)
    else:
        # Fallback: return related products by category
        return get_related_products(product, limit)


def get_related_products(product, limit=6):
    """
    Get related products based on category

    Args:
        product: Product object
        limit: Maximum number of products to return

    Returns:
        QuerySet of related products
    """
    # Get products from the same category
    related = Product.objects.filter(
        category=product.category,
        is_active=True
    ).exclude(
        id=product.id
    )

    # If not enough products, get from parent category
    if related.count() < limit and product.category.parent:
        parent_category_products = Product.objects.filter(
            category=product.category.parent,
            is_active=True
        ).exclude(
            id=product.id
        )
        related = related | parent_category_products

    # If still not enough, get from same brand
    if related.count() < limit:
        brand_products = Product.objects.filter(
            brand=product.brand,
            is_active=True
        ).exclude(
            id=product.id
        )
        related = related | brand_products

    # Sort by rating
    related = related.annotate(
        avg_rating=Coalesce(
            ExpressionWrapper(
                F('reviews__rating__sum') * 1.0 / F('reviews__rating__count'),
                output_field=FloatField()
            ),
            0.0
        )
    ).order_by('-avg_rating', '-created_at')

    return related.distinct()[:limit]


def get_personalized_recommendations(user, limit=10):
    """
    Get personalized product recommendations based on user's purchase history

    Args:
        user: User object
        limit: Maximum number of products to return

    Returns:
        List of recommended products
    """
    if not user.is_authenticated:
        # For guest users, return popular products
        return get_popular_products(limit)

    # Get products the user has purchased
    purchased_products = OrderItem.objects.filter(
        order__user=user
    ).values_list('product_variant__product', flat=True).distinct()

    # Get products the user has viewed but not purchased
    viewed_product_ids = user.request.session.get('viewed_products', [])
    viewed_not_purchased = [pid for pid in viewed_product_ids if pid not in purchased_products]

    # Get categories of purchased products
    purchased_categories = Product.objects.filter(
        id__in=purchased_products
    ).values_list('category', flat=True).distinct()

    # Get highly rated products from these categories
    recommendations = Product.objects.filter(
        category__in=purchased_categories,
        is_active=True
    ).exclude(
        id__in=purchased_products
    ).annotate(
        avg_rating=Coalesce(
            ExpressionWrapper(
                F('reviews__rating__sum') * 1.0 / F('reviews__rating__count'),
                output_field=FloatField()
            ),
            0.0
        )
    ).order_by('-avg_rating')[:limit]

    # If not enough recommendations, add from viewed but not purchased
    if recommendations.count() < limit and viewed_not_purchased:
        viewed_products = Product.objects.filter(
            id__in=viewed_not_purchased,
            is_active=True
        ).exclude(
            id__in=[p.id for p in recommendations]
        )[:limit - recommendations.count()]

        recommendations = list(recommendations) + list(viewed_products)

    # If still not enough, add popular products
    if len(recommendations) < limit:
        popular = get_popular_products(limit - len(recommendations))
        popular_ids = [p.id for p in popular]

        # Exclude products already in recommendations
        popular = [p for p in popular if p.id not in [r.id for r in recommendations]]

        recommendations.extend(popular)

    return recommendations[:limit]


def get_popular_products(limit=10):
    """
    Get popular products based on orders and views

    Args:
        limit: Maximum number of products to return

    Returns:
        QuerySet of popular products
    """
    # Get products with most orders in last 30 days
    thirty_days_ago = timezone.now() - datetime.timedelta(days=30)

    popular = Product.objects.filter(
        orderitem__order__date_ordered__gte=thirty_days_ago,
        is_active=True
    ).annotate(
        order_count=Count('productvariant__orderitem')
    ).order_by('-order_count')[:limit]

    # If not enough products, supplement with highest rated products
    if popular.count() < limit:
        highest_rated = Product.objects.filter(
            is_active=True
        ).exclude(
            id__in=[p.id for p in popular]
        ).annotate(
            avg_rating=Coalesce(
                ExpressionWrapper(
                    F('reviews__rating__sum') * 1.0 / F('reviews__rating__count'),
                    output_field=FloatField()
                ),
                0.0
            )
        ).order_by('-avg_rating')[:limit - popular.count()]

        popular = list(popular) + list(highest_rated)

    return popular


def record_user_activity(user, product=None, category=None, search_term=None, action=None):
    """
    Record user activity for recommendation algorithm

    Args:
        user: User object
        product: Product object (optional)
        category: Category object (optional)
        search_term: Search term (optional)
        action: Action type (view, purchase, add_to_cart, add_to_wishlist)
    """
    # This is a placeholder function
    # In a real implementation, you would store user activity data
    # This could be done using a UserActivity model or an external service

    # Example implementation:
    """
    from .models import UserActivity

    UserActivity.objects.create(
        user=user,
        product=product,
        category=category,
        search_term=search_term,
        action=action,
        timestamp=timezone.now()
    )
    """
    pass