from django.http import HttpResponse, HttpResponseRedirect
from xmodule.modulestore.django import modulestore
from xmodule.modulestore import Location
from models import ContentTest
from capa.capa_problem import LoncapaProblem

#csrf utilities because mako :_(
from django_future.csrf import ensure_csrf_cookie
from django.views.decorators.csrf import csrf_protect
from django.core.context_processors import csrf
from django.contrib.auth.models import User
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from contentstore.views.access import has_access

from xmodule_modifiers import replace_static_urls, wrap_xmodule
from mitxmako.shortcuts import render_to_response


def dict_slice(d, s):
    '''returns dict of that keys that start with "s" (and removing "s" from the keys)'''
    d_slice = {}
    # commented out since it breaks pylint
    # return {k.replace(s, ''): v for k, v in d.iteritems() if k.startswith(s)}
    for k, v in d.iteritems():
        if k.startswith(s):
            d_slice.update([(k.replace(s, ''), v)])
    return d_slice


def secure_fetch(user, model_id):
    """
    fetch model from database and ensure user owns it
    """

    # Fetch from database
    test = ContentTest.objects.get(pk=model_id)

    #ensure user owns this test
    if not has_access(user, Location(test.problem_location)):
        raise PermissionDenied

    return test


@login_required
@ensure_csrf_cookie
def test_problem(request, action=''):
    '''page showing summary of tests for this problem'''

    # location can be specified by post or get
    try:
        problem_location = request.GET['location']
    except:
        problem_location = request.POST['location']

    location = Location(problem_location)

    # check that logged in user has permissions to this item
    if not has_access(request.user, location):
        raise PermissionDenied()

    try:
        modulestore().get_item(location)
    except:
        return HttpResponse("Problem: " + problem_location + "  Doesn't seems to exist :(")

    # switch between the available actions
    if action.lower() == 'delete':
        return delete_test(request)

    elif action.lower() == 'new' or action.lower() == 'edit':
        return edit_test(request)

    elif action.lower() == 'save':
        return save_test(request)

    elif action.lower() == 'run':
        run(location)

    tests = ContentTest.objects.filter(problem_location=location).all()
    for test in tests:
        test.rematch_if_necessary() 

    context = {
        'csrf': csrf(request)['csrf_token'],
        'tests': tests,
        'location': problem_location
    }

    return render_to_response('content_testing/test_summary.html', context)


def delete_test(request):
    """
    delete the specified ContentTest
    """

    # get the problem id from the get data
    id_to_delete = request.POST['id_to_delete']

    #attempt to fetch element from database
    test = secure_fetch(request.user, id_to_delete)

    # delete the test
    test.delete()

    # go back to the main test_problem page
    problem_location = request.POST['location']
    return HttpResponseRedirect('/test_problem/?location='+problem_location)


def edit_test(request):
    """
    display the form for creating/editing a new/existing test
    """

    # get location
    location = request.GET['location']

    # if we are editing an already existing test, we will have an ID
    id_to_edit = request.GET.get('id_to_edit', '')
    if id_to_edit:
        test = secure_fetch(request.user, id_to_edit)
    else:
        test = ContentTest(problem_location=location)

    html = test.get_html_form()
    context = {
        'csrf': csrf(request)['csrf_token'],
        'problem_html': html,
        'location': location,
        'id_to_edit': id_to_edit
    }

    return render_to_response('content_testing/edit_test.html', context)


def save_test(request):
    """
    save a test.  This can be a new test, or an update to an existing one.
    If it is a new test, there will be no `id_to_edit` in the POST data
    """

    post = request.POST
    test_id = post.get('id_to_edit', '')
    response_dict = dict_slice(post, 'input_')
    should_be = post['should_be']
    location = post['location']

    # if we are creating a new problem, create it, else edit existing
    if test_id == '':
        # create new ContentTest
        ContentTest.objects.create(
            problem_location=location,
            response_dict=response_dict,
            should_be=should_be)
    else:
        # Fetch from database
        test = secure_fetch(request.user, test_id)

        # update attributes
        test.should_be = should_be
        test.response_dict = response_dict
        test.save()

    return HttpResponseRedirect('/test_problem/?location='+location)


def run(location):
    """
    runs all tests for the given location and returns the tests
    """

    # get and run all the tests
    tests = ContentTest.objects.filter(problem_location=location)
    for test in tests.all():
        test.run()
