class RequiredSourceUnavailable(RuntimeError):
    code = "required_source_unavailable"


class CatalogBudgetExceeded(RuntimeError):
    code = "catalog_budget_exceeded"
