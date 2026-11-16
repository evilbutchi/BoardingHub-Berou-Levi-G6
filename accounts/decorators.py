from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect


def role_required(*roles):
    """Allow only logged-in users whose role is in `roles`.

    Logged-out users are sent to the login page. Users with another role are
    sent back to their own dashboard with an error message.
    """

    def decorator(view_func):
        @wraps(view_func)
        @login_required
        def wrapper(request, *args, **kwargs):
            if request.user.role not in roles:
                messages.error(request, "You don't have permission to open that page.")
                return redirect(request.user.get_dashboard_url())
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
