import pkgutil

EXTENSIONS = [
    f"{__package__}.{module.name}"
    for module in pkgutil.iter_modules(__path__)
    if not module.name.startswith("_")
]
