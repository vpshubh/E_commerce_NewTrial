from django.db.models import Q, Count, Avg, F
from django.contrib.postgres.search import SearchVector, SearchQuery, SearchRank
from products.models import Product, Category, Brand


def basic_search(query_string, sort_by=None, price_min=None, price_max=None, categories=None, brands=None):
    """
    Basic search implementation using Django's ORM

    Args:
        query_string: The search term entered by the user
        sort_by: Sorting preference (e.g., 'price_low', 'price_high', 'newest', 'rating')
        price_min: Minimum price filter
        price_max: Maximum price filter
        categories: List of category IDs to filter by
        brands: List of brand IDs to filter by

    Returns:
        QuerySet of products matching the search criteria
    """
    # Start with all products
    products = Product.objects.filter(is_active=True)

    # Apply search query if provided
    if query_string:
        # Search in product name, description, and brand name
        products = products.filter(
            Q(name__icontains=query_string) |
            Q(description__icontains=query_string) |
            Q(short_description__icontains=query_string) |
            Q(brand__name__icontains=query_string) |
            Q(category__name__icontains=query_string)
        ).distinct()

    # Apply price filters
    if price_min is not None:
        products = products.filter(base_price__gte=price_min)
    if price_max is not None:
        products = products.filter(base_price__lte=price_max)

    # Apply category filters
    if categories:
        # Include all subcategories of the selected categories
        all_categories = set()
        for cat_id in categories:
            try:
                category = Category.objects.get(id=cat_id)
                # Add the category itself
                all_categories.add(category.id)
                # Add all child categories recursively
                for child in category.get_descendants():
                    all_categories.add(child.id)
            except Category.DoesNotExist:
                pass

        if all_categories:
            products = products.filter(category__id__in=all_categories)

    # Apply brand filters
    if brands:
        products = products.filter(brand__id__in=brands)

    # Apply sorting
    if sort_by:
        if sort_by == 'price_low':
            products = products.order_by('base_price')
        elif sort_by == 'price_high':
            products = products.order_by('-base_price')
        elif sort_by == 'newest':
            products = products.order_by('-created_at')
        elif sort_by == 'rating':
            # Order by average rating
            products = products.annotate(avg_rating=Avg('reviews__rating')).order_by('-avg_rating')
        elif sort_by == 'popularity':
            # Order by number of sales
            products = products.annotate(sales_count=Count('orderitem')).order_by('-sales_count')
        elif sort_by == 'bestseller':
            # Order by number of sales in the last 30 days
            from django.utils import timezone
            import datetime
            thirty_days_ago = timezone.now() - datetime.timedelta(days=30)
            products = products.annotate(
                recent_sales=Count('orderitem', filter=Q(orderitem__order__date_ordered__gte=thirty_days_ago))
            ).order_by('-recent_sales')
    else:
        # Default sorting: featured products first, then by rating
        products = products.annotate(
            avg_rating=Avg('reviews__rating')
        ).order_by('-is_featured', '-avg_rating', 'name')

    return products


def advanced_search(query_string, **filters):
    """
    Advanced search implementation using PostgreSQL full-text search
    Requires PostgreSQL as the database backend

    Args:
        query_string: The search term entered by the user
        **filters: Additional filters as in basic_search

    Returns:
        QuerySet of products matched using full-text search
    """
    if not query_string:
        # Fall back to basic search for filter-only searches
        return basic_search(query_string, **filters)

    # Create a search vector on multiple fields with different weights
    search_vector = (
            SearchVector('name', weight='A') +
            SearchVector('short_description', weight='B') +
            SearchVector('description', weight='C') +
            SearchVector('brand__name', weight='B') +
            SearchVector('category__name', weight='B')
    )

    # Create a search query that looks for all words
    search_query = SearchQuery(query_string)

    # Get products with search ranking
    products = Product.objects.filter(is_active=True).annotate(
        search=search_vector,
        rank=SearchRank(search_vector, search_query)
    ).filter(search=search_query)

    # Apply additional filters from basic_search
    for filter_name, filter_value in filters.items():
        if filter_value is not None:
            if filter_name == 'sort_by':
                # Handle sorting in the final step
                pass
            elif filter_name == 'price_min':
                products = products.filter(base_price__gte=filter_value)
            elif filter_name == 'price_max':
                products = products.filter(base_price__lte=filter_value)
            elif filter_name == 'categories':
                # Include all subcategories of the selected categories
                all_categories = set()
                for cat_id in filter_value:
                    try:
                        category = Category.objects.get(id=cat_id)
                        all_categories.add(category.id)
                        for child in category.get_descendants():
                            all_categories.add(child.id)
                    except Category.DoesNotExist:
                        pass

                if all_categories:
                    products = products.filter(category__id__in=all_categories)
            elif filter_name == 'brands':
                products = products.filter(brand__id__in=filter_value)

    # Apply sorting
    sort_by = filters.get('sort_by')
    if sort_by:
        if sort_by == 'price_low':
            products = products.order_by('base_price')
        elif sort_by == 'price_high':
            products = products.order_by('-base_price')
        elif sort_by == 'newest':
            products = products.order_by('-created_at')
        elif sort_by == 'rating':
            products = products.annotate(avg_rating=Avg('reviews__rating')).order_by('-avg_rating')
        elif sort_by == 'popularity':
            products = products.annotate(sales_count=Count('orderitem')).order_by('-sales_count')
        elif sort_by == 'bestseller':
            from django.utils import timezone
            import datetime
            thirty_days_ago = timezone.now() - datetime.timedelta(days=30)
            products = products.annotate(
                recent_sales=Count('orderitem', filter=Q(orderitem__order__date_ordered__gte=thirty_days_ago))
            ).order_by('-recent_sales')
    else:
        # Default sort by search rank for full-text search
        products = products.order_by('-rank', '-is_featured')

    return products.distinct()


def get_search_facets(products_queryset):
    """
    Get facets (aggregations) for product filtering

    Args:
        products_queryset: The current filtered queryset of products

    Returns:
        Dictionary containing facet information:
        - price_range: min and max prices
        - categories: list of categories with counts
        - brands: list of brands with counts
    """
    # Price range
    from django.db.models import Min, Max
    price_range = products_queryset.aggregate(
        min_price=Min('base_price'),
        max_price=Max('base_price')
    )

    # Categories with counts
    categories = Category.objects.filter(
        products__in=products_queryset
    ).annotate(
        product_count=Count('products', filter=Q(products__in=products_queryset))
    ).values('id', 'name', 'product_count').order_by('-product_count')

    # Brands with counts
    brands = Brand.objects.filter(
        products__in=products_queryset
    ).annotate(
        product_count=Count('products', filter=Q(products__in=products_queryset))
    ).values('id', 'name', 'product_count').order_by('-product_count')

    return {
        'price_range': price_range,
        'categories': list(categories),
        'brands': list(brands)
    }


def get_related_search_terms(query_string):
    """
    Get related search terms based on current query
    Uses product attributes and previous searches

    Args:
        query_string: The current search query

    Returns:
        List of related search terms
    """
    # This is a simplified implementation
    # In a real-world scenario, you might use a more sophisticated approach

    # Find products matching the current query
    products = basic_search(query_string)[:20]  # Limit to first 20 matches

    related_terms = set()

    # Extract terms from product attributes
    for product in products:
        # Add brand as a related term
        if product.brand:
            related_terms.add(product.brand.name)

        # Add category as a related term
        if product.category:
            related_terms.add(product.category.name)

        # Add some words from the product name
        words = [w for w in product.name.split() if len(w) > 3 and w.lower() != query_string.lower()]
        related_terms.update(words[:2])  # Add up to 2 significant words from each product name

    # Remove the original query from related terms
    related_terms.discard(query_string)

    # Convert to list and limit to 10 terms
    return list(related_terms)[:10]