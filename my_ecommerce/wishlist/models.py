from django.db import models
from django.conf import settings
from products.models import Product


class Wishlist(models.Model):
    """
    Wishlist model for users to save products they're interested in
    """
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='wishlists')
    name = models.CharField(max_length=100, default='Default Wishlist')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    is_default = models.BooleanField(default=False)
    is_public = models.BooleanField(default=False)

    class Meta:
        unique_together = ('user', 'name')

    def __str__(self):
        return f"{self.user.username}'s {self.name}"

    def get_item_count(self):
        """Return the number of items in this wishlist"""
        return self.items.count()


class WishlistItem(models.Model):
    """
    Items saved in a user's wishlist
    """
    wishlist = models.ForeignKey(Wishlist, on_delete=models.CASCADE, related_name='items')
    product = models.ForeignKey(Product, on_delete=models.CASCADE)
    date_added = models.DateTimeField(auto_now_add=True)
    note = models.TextField(blank=True, null=True)
    priority = models.PositiveSmallIntegerField(default=0, choices=(
        (0, 'Normal'),
        (1, 'High'),
        (2, 'Highest'),
    ))

    class Meta:
        unique_together = ('wishlist', 'product')
        ordering = ['-priority', 'date_added']

    def __str__(self):
        return f"{self.product.name} in {self.wishlist.name}"


class WishlistShare(models.Model):
    """
    Shared wishlist links with optional password protection
    """
    wishlist = models.ForeignKey(Wishlist, on_delete=models.CASCADE, related_name='shares')
    share_token = models.CharField(max_length=64, unique=True)
    password_protected = models.BooleanField(default=False)
    password_hash = models.CharField(max_length=128, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(blank=True, null=True)

    def __str__(self):
        return f"Share for {self.wishlist.name}"

    def is_expired(self):
        """Check if the share link has expired"""
        if self.expires_at:
            from django.utils import timezone
            return timezone.now() > self.expires_at
        return False