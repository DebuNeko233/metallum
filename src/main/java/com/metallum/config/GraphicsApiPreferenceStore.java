package com.metallum.config;

import com.metallum.Metallum;
import net.fabricmc.loader.api.FabricLoader;

import java.io.IOException;
import java.io.Reader;
import java.io.Writer;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.file.StandardOpenOption;
import java.util.Properties;

/**
 * Early-load-safe storage for the one preference vanilla cannot represent: Prefer Metal.
 * Vanilla remains authoritative for Default/OpenGL/Vulkan.
 */
public final class GraphicsApiPreferenceStore {
    private static final String FILE_NAME = "metallum.properties";
    private static final String KEY = "preferredGraphicsApi";
    private static final String METAL = "metal";
    private static final String DEFAULT = "default";

    private static Boolean metalPreferred;

    private GraphicsApiPreferenceStore() {
    }

    public static synchronized boolean isMetalPreferred() {
        if (metalPreferred == null) {
            metalPreferred = load();
        }
        return metalPreferred;
    }

    public static synchronized void setMetalPreferred(boolean preferred) {
        metalPreferred = preferred;
        save(preferred);
    }

    private static boolean load() {
        Path path = configPath();
        if (!Files.isRegularFile(path)) {
            return false;
        }

        Properties properties = new Properties();
        try (Reader reader = Files.newBufferedReader(path, StandardCharsets.UTF_8)) {
            properties.load(reader);
            return METAL.equalsIgnoreCase(properties.getProperty(KEY, DEFAULT).trim());
        } catch (IOException exception) {
            Metallum.LOGGER.warn("Failed to read {}", path, exception);
            return false;
        }
    }

    private static void save(boolean preferred) {
        Path path = configPath();
        Properties properties = new Properties();
        properties.setProperty(KEY, preferred ? METAL : DEFAULT);

        try {
            Files.createDirectories(path.getParent());
            try (Writer writer = Files.newBufferedWriter(
                    path,
                    StandardCharsets.UTF_8,
                    StandardOpenOption.CREATE,
                    StandardOpenOption.TRUNCATE_EXISTING,
                    StandardOpenOption.WRITE
            )) {
                properties.store(writer, "Metallum graphics API preference");
            }
        } catch (IOException exception) {
            Metallum.LOGGER.error("Failed to write {}", path, exception);
        }
    }

    private static Path configPath() {
        return FabricLoader.getInstance().getConfigDir().resolve(FILE_NAME);
    }
}
