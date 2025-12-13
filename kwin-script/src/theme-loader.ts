/**
 * Theme loader for KWin overlay
 *
 * Loads theme JSON and applies to QML components
 */

export interface ThemeColors {
    background: string;
    surface: string;
    primary: string;
    secondary: string;
    text: string;
    border: string;
    highlight: string;
}

export interface ThemeEffects {
    blurRadius: number;
    backgroundOpacity: number;
    saturation: number;
    noiseOpacity: number;
    borderOpacity: number;
    glowEnabled: boolean;
    glowColor?: string;
}

export interface ThemeAnimation {
    appearMs: number;
    dismissMs: number;
    highlightInMs: number;
    highlightOutMs: number;
}

export interface Theme {
    name: string;
    displayName: string;
    colors: ThemeColors;
    effects: ThemeEffects;
    animation: ThemeAnimation;
}

/**
 * Default Catppuccin Mocha theme
 */
export const DEFAULT_THEME: Theme = {
    name: 'catppuccin-mocha',
    displayName: 'Catppuccin Mocha',
    colors: {
        background: '#1e1e2e',
        surface: '#313244',
        primary: '#cba6f7',
        secondary: '#f5c2e7',
        text: '#cdd6f4',
        border: '#45475a',
        highlight: '#89b4fa'
    },
    effects: {
        blurRadius: 24,
        backgroundOpacity: 0.75,
        saturation: 1.8,
        noiseOpacity: 0.04,
        borderOpacity: 0.3,
        glowEnabled: true,
        glowColor: '#cba6f7'
    },
    animation: {
        appearMs: 30,
        dismissMs: 50,
        highlightInMs: 80,
        highlightOutMs: 60
    }
};

/**
 * Theme loader class
 */
export class ThemeLoader {
    private currentTheme: Theme = DEFAULT_THEME;
    private availableThemes: Map<string, Theme> = new Map();

    constructor() {
        // Register default theme
        this.availableThemes.set(DEFAULT_THEME.name, DEFAULT_THEME);
    }

    /**
     * Load theme from JSON file
     */
    load(themeName: string): Theme | null {
        const theme = this.availableThemes.get(themeName);
        if (theme) {
            this.currentTheme = theme;
            return theme;
        }

        // TODO: Load from file system
        console.log(`Theme not found: ${themeName}`);
        return null;
    }

    /**
     * Get current theme
     */
    getCurrent(): Theme {
        return this.currentTheme;
    }

    /**
     * Register a theme
     */
    register(theme: Theme): void {
        this.availableThemes.set(theme.name, theme);
    }

    /**
     * Get list of available theme names
     */
    getAvailable(): string[] {
        return Array.from(this.availableThemes.keys());
    }
}

export const themeLoader = new ThemeLoader();
