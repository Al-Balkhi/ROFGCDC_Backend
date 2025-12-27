from rest_framework.pagination import PageNumberPagination


class OptimizationPagination(PageNumberPagination):
    """
    Pagination class for optimization list views.
    Page size is fixed at 7 items per page.
    """

    page_size = 7
    page_size_query_param = None  # Disable client-side page size control

