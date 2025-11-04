package stepDefinitions;

import io.cucumber.java.en.When;
import io.cucumber.java.BeforeAll;
import io.restassured.response.Response;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.fasterxml.jackson.core.type.TypeReference;

import java.nio.file.*;
import java.util.*;
import java.util.stream.Collectors;

public class ExecStepDef extends RootStepDef {

    // RAM cache: "step name" (lowercase, single-space) -> "SEQ,SEQ"
    private static Map<String, String> STEP_TO_SEQ = Collections.emptyMap();
    private static Path SEQ_PATH;
    private static long LAST_MTIME = -1L;

    @BeforeAll
    public static void loadSequencesOnce() throws Exception {
        SEQ_PATH = resolveSequencesPath();
        reloadIfChanged(); // prvé načítanie
    }

    @When("exec {string}")
    public void exec(String scenarioName) {
        // (voliteľné) hot-reload: ak počas dlhého behu zmeníš sequences.json, znova ho načítame
        reloadIfChanged();

        String key = normalizeStepName(scenarioName);
        String sequence = STEP_TO_SEQ.get(key);
        if (sequence == null) {
            throw new NoSuchElementException("Scenario not found in sequences.json: \"" + key + "\"");
        }

        // Tvoje existujúce volania z RootStepDef:
        Response response = PostToSequenceExec(sequence);
        Validate(response);
    }

    // ==================== interné helpery (nič v Root-e meniť netreba) ====================

    /** Nájde sequences.json: 1) -Dsequences.path=..., 2) classpath (src/test/resources), 3) ./sequences.json */
    private static Path resolveSequencesPath() throws Exception {
        String prop = System.getProperty("sequences.path");
        if (prop != null && !prop.isBlank()) {
            Path p = Paths.get(prop);
            if (Files.exists(p)) return p;
            throw new IllegalArgumentException("sequences.path points to non-existing file: " + p);
        }
        try {
            var url = ExecStepDef.class.getClassLoader().getResource("sequences.json");
            if (url != null) return Paths.get(url.toURI());
        } catch (Exception ignore) {}
        Path root = Paths.get("sequences.json");
        if (Files.exists(root)) return root;
        throw new IllegalStateException(
                "Could not find sequences.json. Provide it on classpath, project root, or via -Dsequences.path=..."
        );
    }

    /** Načíta JSON a vybuduje RAM index "step -> seq" (oba normalizované ako v Pythone). */
    private static Map<String, String> loadStepToSeq(Path path) throws Exception {
        ObjectMapper om = new ObjectMapper();
        Map<String,Object> root = om.readValue(Files.newBufferedReader(path), new TypeReference<Map<String,Object>>(){});
        @SuppressWarnings("unchecked")
        Map<String, List<String>> map = (Map<String, List<String>>) root.getOrDefault("map", Map.of());

        Map<String, String> rev = new HashMap<>();
        for (var e : map.entrySet()) {
            String seq = canonicalizeSequence(e.getKey()); // "down ,  enter" -> "DOWN,ENTER"
            for (String stepRaw : e.getValue()) {
                String step = normalizeStepName(stepRaw);   // "Open   Menu" -> "open menu"
                String prev = rev.putIfAbsent(step, seq);
                if (prev != null && !prev.equals(seq)) {
                    throw new IllegalStateException(
                            "Step \"" + step + "\" appears under [" + prev + "] and [" + seq + "]."
                    );
                }
            }
        }
        return Collections.unmodifiableMap(rev);
    }

    /** Ak sa zmenil mtime súboru, znova načítaj cache. */
    private static void reloadIfChanged() {
        try {
            long m = Files.getLastModifiedTime(SEQ_PATH).toMillis();
            if (m != LAST_MTIME) {
                STEP_TO_SEQ = loadStepToSeq(SEQ_PATH);
                LAST_MTIME = m;
            }
        } catch (Exception e) {
            throw new RuntimeException("Failed to (re)load sequences from " + SEQ_PATH, e);
        }
    }

    // ===== rovnaké pravidlá ako v tvojom Pythone =====

    // názov scenára: iba lowercase písmená/čísla + JEDNA medzera medzi slovami
    private static final String NAME_REGEX = "[a-z0-9]+(?: [a-z0-9]+)*";

    /** Zrazí viac medzier na jednu, prekonvertuje na lowercase a overí regex. */
    private static String normalizeStepName(String raw) {
        if (raw == null) throw new IllegalArgumentException("Step name is null.");
        String s = raw.toLowerCase(Locale.ROOT).trim().replaceAll("\\s+", " ");
        if (!s.matches(NAME_REGEX)) {
            throw new IllegalArgumentException(
                    "Invalid step name. Allowed: lowercase letters/digits with single spaces (no punctuation). Raw: " + raw
            );
        }
        return s;
    }

    /** Rozdelí podľa čiarky/whitespace, oreže, upper, spojí čiarkou: TOKEN,TOKEN. */
    private static String canonicalizeSequence(String raw) {
        if (raw == null) throw new IllegalArgumentException("Sequence is null.");
        String[] toks = raw.trim().split("[,\\s]+");
        List<String> out = Arrays.stream(toks)
                .filter(t -> !t.isEmpty())
                .map(t -> t.toUpperCase(Locale.ROOT))
                .collect(Collectors.toList());
        if (out.isEmpty()) throw new IllegalArgumentException("Empty sequence.");
        return String.join(",", out);
    }
}
