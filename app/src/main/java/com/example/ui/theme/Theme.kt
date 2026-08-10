package com.example.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable

private val HighDensityColorScheme = lightColorScheme(
    primary = HighDensityNavy,
    onPrimary = HighDensitySurface,
    secondary = HighDensitySecondary,
    onSecondary = HighDensitySurface,
    tertiary = HighDensityWarning,
    background = HighDensityBackground,
    onBackground = HighDensityTextPrimary,
    surface = HighDensitySurface,
    onSurface = HighDensityTextPrimary,
    surfaceVariant = HighDensitySurfaceVariant,
    onSurfaceVariant = HighDensityTextSecondary,
    error = HighDensityEmergency,
    onError = HighDensitySurface,
    outline = HighDensityBorder
)

@Composable
fun MyApplicationTheme(
    darkTheme: Boolean = isSystemInDarkTheme(),
    dynamicColor: Boolean = false,
    content: @Composable () -> Unit
) {
    MaterialTheme(
        colorScheme = HighDensityColorScheme,
        typography = Typography,
        content = content
    )
}

