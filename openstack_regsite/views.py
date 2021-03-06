# Copyright 2015 Hungarian Academy of Sciences
#                Institute for Computer Science and Control
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

# This file contains the views of the regsite app
from django.http import HttpResponse
from django.shortcuts import redirect
from django.shortcuts import render_to_response
from django.conf import settings

import json

import utils
import logging


logger = logging.getLogger('openstack_regsite')

# Extract the attributes from the request


def _get_attrs(request):
    eppn = request.META.get(settings.SHIBBOLETH_NAME_ATTRIBUTE, None)
    entitlement = request.META.get(
        settings.SHIBBOLETH_ENTITLEMENT_ATTRIBUTE, None)
    email = request.META.get(settings.SHIBBOLETH_EMAIL_ATTRIBUTE, None)

    return eppn, entitlement, email

# Update the user in keystone from the given attributes


def _update_user(request):
    pw = None
    eppn, entitlement, email = _get_attrs(request)
    next_page = request.GET.get('return', '/')
    if request.method == "POST":
        pw = request.POST.get('password')
    utils.update_user(
        username=eppn,
        entitlement=entitlement,
        mail=email,
        password=pw)
    # redirect to the Shibboleth HOOK return url.
    return redirect(next_page)

# The user creation page.


def _show_user_creation_page(request):
    eppn, entitlement, email = _get_attrs(request)
    shibboleth_entitlement = utils.parse_entitlements(entitlement)
    if shibboleth_entitlement is not None:
        shibboleth_entitlement = dict(shibboleth_entitlement)
    else:
        shibboleth_entitlement = ["You are not authorized for any projects."]
    attributes = {
        'openstack_servername': settings.OPENSTACK_NAME,
        'openstack_url': settings.OPENSTACK_URL,
        'openstack_keystone': settings.OPENSTACK_KEYSTONE_ADMIN_URL,
        'shibboleth_name': eppn,
        'shibboleth_entitlement': shibboleth_entitlement,
        'return': request.GET.get('return', '/'),
        'target': request.GET.get('target', None),
        'base_url': settings.BASE_URL,
        'password_set_enabled': settings.PASSWORD_SET_ENABLED,
    }

    return render_to_response('regsite/index.html', attributes)


def _deprovision_hook(request):
    # Process the deprovisiong from the AA.
    if request.method == "POST":
        hook_json = json.loads(request.body)
        # Check for a hook key for authentication
        if 'key' in hook_json.keys(
        ) and hook_json['key'] == settings.SHIBBOLETH_HOOK_KEY:
            # If the action was attribute_change update the user in keystone
            # based on the data received
            if hook_json['action'] == 'attribute_change':
                for eppn in hook_json['data']:
                    entitlement = None
                    for attribute in hook_json['data'][eppn]:
                        if attribute == settings.SHIBBOLETH_ENTITLEMENT_ID:
                            for attr_value in hook_json['data'][eppn][attribute]:
                                if entitlement is None:
                                    entitlement = attr_value
                                else:
                                    entitlement += ';' + attr_value
                    username = utils.update_user(
                        username=eppn, entitlement=entitlement)
                return HttpResponse(username)
            # If the action was user_removed delete the user from all project
            # in keystone, but keep the user.
            if hook_json['action'] == 'user_removed':
                for eppn in hook_json['data']:
                    username = utils.update_user(
                        username=eppn, entitlement=None)
                return HttpResponse(username)

def _get_circle_attrs(request):
    idp = request.META.get('Shib-Identity-Provider')
    domain = settings.OPENSTACK_CIRCLE_IDPS_MAPPING[idp]
    neptun = request.META.get(settings.SHIBBOLETH_CIRCLE_NEPTUN_ATTRIBUTE)
    email = request.META.get(settings.SHIBBOLETH_CIRCLE_EMAIL_ATTRIBUTE)
    attendedCourses = request.META.get(settings.SHIBBOLETH_CIRCLE_ATTENDEDCOURSES_ATTRIBUTE, [])
    heldCourses = request.META.get(settings.SHIBBOLETH_CIRCLE_HELDCOURSES_ATTRIBUTE, [])

    if type(attendedCourses) == str:
        attendedCourses = attendedCourses.split(settings.SHIBBOLETH_CIRCLE_COURSE_DELIMITER)

    if type(heldCourses) == str:
        heldCourses = heldCourses.split(settings.SHIBBOLETH_CIRCLE_COURSE_DELIMITER)

    return domain, neptun, email, attendedCourses, heldCourses

def handleCircleSessionHook(request):
    domain, neptun, email, attendedCourses, heldCourses = _get_circle_attrs(request)
    next_page = request.GET.get('return', '/')

    utils.update_circle_user(
        domain,
        neptun,
        email,
        attendedCourses,
        heldCourses
    )

    return redirect(next_page)

def handleNormalSessionHook(request):
    eppn, entitlement, email = _get_attrs(request)

    # If the eppn attribute is missing show an error
    if eppn is None:
        return render_to_response(
            'regsite/missing_attribute.html',
            {'message': settings.MISSING_EPPN_MESSAGE}, status=500)
    # If the entitlement is missing show an error
    if entitlement is None and not utils.user_exists(eppn):
        return render_to_response(
            'regsite/missing_attribute.html',
            {'message': settings.MISSING_ENTITLEMENT_MESSAGE}, status=500)
    # If the user consent page is disabled or the user exists in keystone
    # update the user silently in keystone.
    if not settings.USER_ACCEPT_CREATION or utils.user_exists(eppn):
        return _update_user(request)
    # Otherwise show the user creation page
    else:
        return _show_user_creation_page(request)

# The index page
def index(request):
    # if the current IdP is for CIRCLE module usage
    if request.META.get('Shib-Identity-Provider', None) in settings.OPENSTACK_CIRCLE_IDPS_MAPPING.keys():
        return handleCircleSessionHook(request)
    else:
        return handleNormalSessionHook(request)

# This is the callback of shibboleth hook
def shib_hook(request):
    return _update_user(request=request)

# Deprpovisioning hook
def deprovision(request):
    return _deprovision_hook(request)
