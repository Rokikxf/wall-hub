import ipaddress

from django import forms

from inventory.models import Device, Licence, Location, Person


class BootstrapForm:
    """Mixin: give every widget its Bootstrap class, so _fields.html can render any form."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for field in self.fields.values():
            widget = field.widget
            if isinstance(widget, forms.CheckboxInput):
                css = "form-check-input"
            elif isinstance(widget, forms.Select | forms.SelectMultiple):
                css = "form-select"
            else:
                css = "form-control"
            widget.attrs.setdefault("class", css)


def date_input():
    return forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")


class MonitoringForm(forms.ModelForm):
    class Meta:
        model = Device
        fields = ["monitored", "check_port"]
        labels = {"monitored": "Monitor this device", "check_port": "Check TCP port"}


class DeviceAssetForm(BootstrapForm, forms.ModelForm):
    class Meta:
        model = Device
        fields = [
            "name",
            "kind",
            # Empty is saved as NULL (asset_tag is null=True), so the unique column
            # allows any number of untagged devices.
            "asset_tag",
            "owner",
            "location",
            "manufacturer",
            "model_name",
            "serial_number",
            "purchase_date",
            "warranty_expires",
            "notes",
        ]
        widgets = {
            "purchase_date": date_input(),
            "warranty_expires": date_input(),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }


class DeviceFilterForm(BootstrapForm, forms.Form):
    q = forms.CharField(required=False, label="Search")
    kind = forms.ChoiceField(
        required=False, label="Type", choices=[("", "Any type"), *Device.Kind.choices]
    )
    owner = forms.ModelChoiceField(
        required=False, queryset=Person.objects.all(), empty_label="Any owner"
    )
    location = forms.ModelChoiceField(
        required=False, queryset=Location.objects.all(), empty_label="Any location"
    )


class PersonForm(BootstrapForm, forms.ModelForm):
    class Meta:
        model = Person
        fields = ["name", "email", "department", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class LocationForm(BootstrapForm, forms.ModelForm):
    class Meta:
        model = Location
        fields = ["name", "notes"]
        widgets = {"notes": forms.Textarea(attrs={"rows": 3})}


class DeviceChoiceField(forms.ModelMultipleChoiceField):
    def label_from_instance(self, device):
        name = str(device)
        return name if name == device.ip else f"{name} ({device.ip})"


class LicenceForm(BootstrapForm, forms.ModelForm):
    devices = DeviceChoiceField(
        required=False,
        queryset=Device.objects.all(),
        widget=forms.SelectMultiple(attrs={"size": 8}),
        help_text="Devices using a seat, e.g. for licences sold per computer.",
    )

    class Meta:
        model = Licence
        fields = [
            "name",
            "vendor",
            "licence_key",
            "seats",
            "purchase_date",
            "expires",
            "people",
            "devices",
            "notes",
        ]
        widgets = {
            "licence_key": forms.Textarea(attrs={"rows": 2}),
            "purchase_date": date_input(),
            "expires": date_input(),
            "people": forms.SelectMultiple(attrs={"size": 8}),
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
        help_texts = {"people": "People using a seat, e.g. for licences sold per user."}


# The same limits wall-scan enforces, checked here so the user gets a clear message
# before a scan is queued rather than a failed scan afterwards.
LARGEST_PREFIX = 16


class ScanForm(forms.Form):
    targets = forms.CharField(
        max_length=500,
        help_text="IPv4 addresses or CIDR ranges, separated by spaces, e.g. 192.168.1.0/24",
    )

    def clean_targets(self) -> str:
        tokens = self.cleaned_data["targets"].replace(",", " ").split()
        if not tokens:
            raise forms.ValidationError("Enter at least one address or range.")
        for token in tokens:
            try:
                network = ipaddress.IPv4Network(token, strict=False)
            except ValueError:
                raise forms.ValidationError(
                    f"{token} is not an IPv4 address or CIDR range."
                ) from None
            if network.prefixlen < LARGEST_PREFIX:
                raise forms.ValidationError(f"{token} is larger than a /{LARGEST_PREFIX}.")
            if not network.is_private:
                raise forms.ValidationError(f"{token} is not a private address range.")
        return " ".join(tokens)
