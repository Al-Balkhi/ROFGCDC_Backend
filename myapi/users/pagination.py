from rest_framework.pagination import PageNumberPagination


class UserPagination(PageNumberPagination):
    """
    Pagination class for user list views.
    Page size is fixed at 15 users per page.
    """

    page_size = 15
    page_size_query_param = None  # Disable client-side page size control

