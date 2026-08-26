from core.services import ReadMixin, ServiceBase
from base.models import Country


class CountryService(ReadMixin, ServiceBase[Country]):
    """Read-only: countries come from the system fixture, no controller writes them."""
