"""Bus factory for creating provider instances based on configuration."""

from typing import Literal

from loguru import logger

from aisbot.bus.provider import BusProvider, BusType
from aisbot.bus.dds_provider import DDSProvider
from aisbot.bus.zenoh_provider import ZenohProvider


class BusFactory:
    """
    Factory for creating message bus providers.

    Provides a unified interface to create different types of bus providers
    (DDS, Zenoh) based on configuration.
    """

    _providers: dict[BusType, type[BusProvider]] = {
        BusType.DDS: DDSProvider,
        BusType.ZENOH: ZenohProvider,
    }

    @classmethod
    def create(cls, bus_type: BusType | str, **kwargs) -> BusProvider:
        """
        Create a bus provider instance.

        Args:
            bus_type: Type of bus to create ("dds" or "zenoh").
            **kwargs: Additional arguments passed to the provider constructor.

        Returns:
            A configured BusProvider instance.

        Raises:
            ValueError: If the bus type is not supported.
        """
        # Convert string to BusType if needed
        if isinstance(bus_type, str):
            bus_type = BusType(bus_type.lower())

        provider_class = cls._providers.get(bus_type)
        if not provider_class:
            raise ValueError(
                f"Unsupported bus type: {bus_type}. "
                f"Supported types: {[t.value for t in BusType]}"
            )

        logger.info(f"Creating {bus_type.value} provider")
        return provider_class(**kwargs)

    @classmethod
    def register(cls, bus_type: BusType, provider_class: type[BusProvider]) -> None:
        """
        Register a new provider type.

        Args:
            bus_type: The BusType enum value.
            provider_class: The provider class to register.
        """
        cls._providers[bus_type] = provider_class
        logger.info(f"Registered provider for bus type: {bus_type.value}")

    @classmethod
    def supported_types(cls) -> list[str]:
        """Get list of supported bus types."""
        return [t.value for t in BusType]


def create_bus(
    bus_type: Literal["dds", "zenoh"] | BusType = "dds", **kwargs
) -> BusProvider:
    """
    Convenience function to create a bus provider.

    Args:
        bus_type: Type of bus to create.
        **kwargs: Additional arguments passed to the provider.

    Returns:
        A configured BusProvider instance.
    """
    return BusFactory.create(bus_type, **kwargs)
