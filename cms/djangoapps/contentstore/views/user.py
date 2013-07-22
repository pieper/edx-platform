import json
from django.conf import settings
from django.core.exceptions import PermissionDenied
from django.contrib.auth.models import User, Group
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_http_methods
from django.utils.translation import ugettext as _
from django_future.csrf import ensure_csrf_cookie
from mitxmako.shortcuts import render_to_response

from xmodule.modulestore import Location
from xmodule.modulestore.django import modulestore
from contentstore.utils import get_url_reverse, get_lms_link_for_item
from util.json_request import JsonResponse
from auth.authz import (
    STAFF_ROLE_NAME, INSTRUCTOR_ROLE_NAME, get_users_in_course_group_by_role,
    add_user_to_course_group, remove_user_from_course_group,
    get_course_groupname_for_role)

from .access import has_access


@login_required
@ensure_csrf_cookie
def index(request):
    """
    List all courses available to the logged in user
    """
    courses = modulestore('direct').get_items(['i4x', None, None, 'course', None])

    # filter out courses that we don't have access too
    def course_filter(course):
        return (has_access(request.user, course.location)
                # TODO remove this condition when templates purged from db
                and course.location.course != 'templates'
                and course.location.org != ''
                and course.location.course != ''
                and course.location.name != '')
    courses = filter(course_filter, courses)

    return render_to_response('index.html', {
        'courses': [(course.display_name,
                    get_url_reverse('CourseOutline', course),
                    get_lms_link_for_item(course.location, course_id=course.location.course_id))
                    for course in courses],
        'user': request.user,
        'disable_course_creation': settings.MITX_FEATURES.get('DISABLE_COURSE_CREATION', False) and not request.user.is_staff
    })


@login_required
@ensure_csrf_cookie
def manage_users(request, org, course, name):
    '''
    This view will return all CMS users who are editors for the specified course
    '''
    location = Location('i4x', org, course, 'course', name)
    # check that logged in user has permissions to this item
    if not has_access(request.user, location, role=INSTRUCTOR_ROLE_NAME) and not has_access(request.user, location, role=STAFF_ROLE_NAME):
        raise PermissionDenied()

    course_module = modulestore().get_item(location)

    return render_to_response('manage_users.html', {
        'context_course': course_module,
        'staff': get_users_in_course_group_by_role(location, STAFF_ROLE_NAME),
        'allow_actions': has_access(request.user, location, role=INSTRUCTOR_ROLE_NAME),
    })


@login_required
@ensure_csrf_cookie
@require_http_methods(("GET", "POST", "PUT", "DELETE"))
def course_team_user(request, org, course, name, email):
    location = Location('i4x', org, course, 'course', name)
    # check that logged in user has permissions to this item
    if not has_access(request.user, location, role=INSTRUCTOR_ROLE_NAME) and not has_access(request.user, location, role=STAFF_ROLE_NAME):
        raise PermissionDenied()

    try:
        user = User.objects.get(email=email)
    except:
        msg = {
            "error": _("Could not find user by email address '{email}'.").format(email=email),
        }
        return JsonResponse(msg, 404)

    if request.method == "GET":
        # just return info about the user
        roles = set()
        for group in user.groups.all():
            if not "_" in group.name:
                continue
            role, coursename = group.name.split("_", 1)
            if coursename in (location.course, location.course_id):
                roles.add(role)
        msg = {
            "email": user.email,
            "active": user.is_active,
            "roles": list(roles),
        }
        return JsonResponse(msg)

    # can't modify an inactive user
    if not user.is_active:
        msg = {
            "error": _('User {email} has registered but has not yet activated his/her account.').format(email=email),
        }
        return JsonResponse(msg, 400)

    # all other operations require the requesting user to specify a role --
    # or if no role is specified, default to "staff"
    if not request.body:
        role = STAFF_ROLE_NAME
    else:
        try:
            payload = json.loads(request.body)
        except:
            return JsonResponse({"error": _("malformed JSON")}, 400)
        try:
            role = payload["role"]
        except KeyError:
            return JsonResponse({"error": "`role` is required"}, 400)
    groupname = get_course_groupname_for_role(location, role)
    group = Group.objects.get_or_create(name=groupname)

    if request.method in ("POST", "PUT"):
        add_user_to_course_group(request.user, user, location, role)
        return JsonResponse()
    elif request.method == "DELETE":
        remove_user_from_course_group(request.user, user, location, role)
        return JsonResponse()
