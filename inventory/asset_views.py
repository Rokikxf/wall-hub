"""Asset management pages: device asset details, people, locations, licences, expiry.

Create and edit pages share inventory/form.html and delete pages share
inventory/confirm_delete.html; list and detail pages have their own templates.
"""

from datetime import timedelta

from django.conf import settings
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.messages.views import SuccessMessageMixin
from django.db.models import Count
from django.urls import reverse_lazy
from django.utils import timezone
from django.views.generic import (
    CreateView,
    DeleteView,
    DetailView,
    ListView,
    TemplateView,
    UpdateView,
)

from inventory import expiry
from inventory.forms import DeviceAssetForm, LicenceForm, LocationForm, PersonForm
from inventory.models import Device, Licence, Location, Person

EXPIRING_WINDOW = timedelta(days=90)


class FormPage(LoginRequiredMixin, SuccessMessageMixin):
    """A create or edit page. Subclasses set model, form_class and list_url."""

    template_name = "inventory/form.html"
    success_message = "Saved."
    list_url = None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        editing = getattr(self, "object", None) is not None
        context["title"] = self.page_title() if editing else f"New {self.model._meta.verbose_name}"
        context["cancel_url"] = self.object.get_absolute_url() if editing else self.list_url
        return context

    def page_title(self) -> str:
        return f"Edit {self.object}"


class DeletePage(LoginRequiredMixin, SuccessMessageMixin, DeleteView):
    template_name = "inventory/confirm_delete.html"

    def get_success_message(self, cleaned_data):
        return f"Deleted {self.object}."


# --- devices ---


class DeviceAssetUpdate(FormPage, UpdateView):
    model = Device
    form_class = DeviceAssetForm

    def page_title(self) -> str:
        return f"Asset details of {self.object}"


# --- people ---


class PersonList(LoginRequiredMixin, ListView):
    queryset = Person.objects.annotate(
        device_count=Count("devices", distinct=True),
        licence_count=Count("licences", distinct=True),
    )


class PersonDetail(LoginRequiredMixin, DetailView):
    model = Person


class PersonCreate(FormPage, CreateView):
    model = Person
    form_class = PersonForm
    list_url = reverse_lazy("person-list")


class PersonUpdate(FormPage, UpdateView):
    model = Person
    form_class = PersonForm


class PersonDelete(DeletePage):
    model = Person
    success_url = reverse_lazy("person-list")
    extra_context = {"note": "Their devices will have no owner, and their licence seats are freed."}


# --- locations ---


class LocationList(LoginRequiredMixin, ListView):
    queryset = Location.objects.annotate(device_count=Count("devices"))


class LocationDetail(LoginRequiredMixin, DetailView):
    model = Location


class LocationCreate(FormPage, CreateView):
    model = Location
    form_class = LocationForm
    list_url = reverse_lazy("location-list")


class LocationUpdate(FormPage, UpdateView):
    model = Location
    form_class = LocationForm


class LocationDelete(DeletePage):
    model = Location
    success_url = reverse_lazy("location-list")
    extra_context = {"note": "Its devices will have no location."}


# --- licences ---


class LicenceList(LoginRequiredMixin, ListView):
    queryset = Licence.objects.annotate(
        used=Count("people", distinct=True) + Count("devices", distinct=True)
    )


class LicenceDetail(LoginRequiredMixin, DetailView):
    model = Licence


class LicenceCreate(FormPage, CreateView):
    model = Licence
    form_class = LicenceForm
    list_url = reverse_lazy("licence-list")


class LicenceUpdate(FormPage, UpdateView):
    model = Licence
    form_class = LicenceForm


class LicenceDelete(DeletePage):
    model = Licence
    success_url = reverse_lazy("licence-list")
    extra_context = {"note": "Its key and assignments are deleted with it."}


# --- expiry ---


class Expiring(LoginRequiredMixin, TemplateView):
    """Warranties and licences ending in the next 90 days, or ended in the last 90."""

    template_name = "inventory/expiring.html"

    def get_context_data(self, **kwargs):
        today = timezone.localdate()
        upcoming = expiry.between(today, today + EXPIRING_WINDOW)
        ended = expiry.between(today - EXPIRING_WINDOW, today - timedelta(days=1))
        return super().get_context_data(
            window_days=EXPIRING_WINDOW.days,
            reminder_days=settings.WALL_EXPIRY_REMINDER_DAYS,
            upcoming=[(item, item.days_left(today)) for item in upcoming],
            ended=[(item, -item.days_left(today)) for item in reversed(ended)],
            **kwargs,
        )
