"""Template context shared by every page."""


def citizen(request):
    """Expose the signed-in citizen, if there is one.

    The navbar needs this on every page, and citizen login is optional, so
    threading it through each view by hand would be noise.
    """

    from .views import get_logged_in_citizen

    return {
        "current_citizen": get_logged_in_citizen(request),
    }
