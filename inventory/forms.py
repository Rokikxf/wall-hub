import ipaddress

from django import forms

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
