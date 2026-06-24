# generate_paper_plots.R
# Produces paper-quality plots for TSP_Paper.tex from batch_results.csv
# With multiple seeds per experiment, all numeric metrics are averaged across
# seeds before plotting.  Error bars (95% CI) are added where n_seeds >= 2.
library(tidyverse)
library(scales)
library(patchwork)

theme_paper <- theme_minimal(base_size = 11) +
  theme(plot.background = element_rect(fill = "white", color = NA),
        panel.background = element_rect(fill = "white"),
        text = element_text(color = "black"),
        axis.text = element_text(color = "black", size = 9),
        panel.grid = element_line(color = "gray90"),
        legend.background = element_rect(fill = "white"),
        legend.text = element_text(color = "black", size = 9),
        plot.title = element_text(size = 13, face = "bold"),
        plot.subtitle = element_text(size = 10, color = "gray40"))

theme_set(theme_paper)

batch <- read_csv("batch_results.csv", show_col_types = FALSE)

# Rename key columns
df_raw <- batch %>%
  rename(
    experiment      = run_experiment,
    seed            = run_seed,
    pass_delay_hrs  = stats_TotalPassDelay_hrs,
    main_delay_hrs  = stats_MainPassDelay_hrs,
    side_delay_hrs  = stats_SidePassDelay_hrs,
    bus_delay_s     = stats_AvgBusPassDelay_s,
    car_delay_s     = stats_AvgCarPassDelay_s,
    speed_kmh       = stats_Net_AvgSpeed_kmh,
    detections      = stats_TSP_Detections,
    extensions      = stats_TSP_Extensions,
    insertions      = stats_TSP_Insertions
  ) %>%
  mutate(grant_rate = (extensions + insertions) / pmax(detections, 1))

# ── Seed averaging ─────────────────────────────────────────────────────────────
# For every experiment group by name and compute mean + sd across seeds.
# All downstream plots use df (averaged) or df_raw (per-seed, for ribbon/CI plots).
df <- df_raw %>%
  group_by(experiment) %>%
  summarise(
    n_seeds        = n(),
    across(where(is.numeric) & !matches("^seed$"), ~ mean(.x, na.rm = TRUE),
           .names = "{.col}"),
    # Standard deviation columns for CI error bars (suffix _sd)
    pass_delay_sd  = sd(pass_delay_hrs, na.rm = TRUE),
    bus_delay_sd   = sd(bus_delay_s,    na.rm = TRUE),
    car_delay_sd   = sd(car_delay_s,    na.rm = TRUE),
    main_delay_sd  = sd(main_delay_hrs, na.rm = TRUE),
    side_delay_sd  = sd(side_delay_hrs, na.rm = TRUE),
    .groups = "drop"
  )

# Helper: 95% CI half-width from sd and n
ci95 <- function(sd, n) qt(0.975, pmax(n - 1, 1)) * sd / sqrt(pmax(n, 1))

# Baseline: mean of NO_TSP seeds
no_tsp <- df %>% filter(experiment == "NO_TSP")
base_delay <- no_tsp$pass_delay_hrs
base_bus   <- no_tsp$bus_delay_s
base_car   <- no_tsp$car_delay_s
base_main  <- no_tsp$main_delay_hrs
base_side  <- no_tsp$side_delay_hrs

# Strategy subset (update experiment names to match current batch)
STRAT_NAMES <- c(
  "NO_TSP", "DCTSP_MARL", "DCTSP_MARL_HS", "DCTSP_ZIG",
  "DCTSP_BARGAIN_SPM", "DCTSP_MP_ECTM", "DCTSP_BXT",
  "PRED_BARGAIN_KALMAN", "PRED_BARGAIN_ADAPTIVE_KALMAN", "PRED_BARGAIN_LSTM_SS",
  "PRED_ADAPTIVE_KALMAN_WaveGate", "PRED_ADAPTIVE_KALMAN_NashGate", "PRED_ADAPTIVE_KALMAN_MambaATSP",
  "PRED_LSTM_SS_WaveGate", "PRED_LSTM_SS_NashGate", "PRED_LSTM_SS_MambaATSP"
)

STRAT_LABELS <- c(
  "NO_TSP"                           = "NoPriority",
  "DCTSP_MARL"                       = "CPD-QL",
  "DCTSP_MARL_HS"                    = "CPD-QL-HS",
  "DCTSP_ZIG"                        = "WaveGate",
  "DCTSP_BARGAIN_SPM"                = "NashGate",
  "DCTSP_MP_ECTM"                    = "CellSearch",
  "DCTSP_BXT"                        = "CellQLearn",
  "PRED_BARGAIN_KALMAN"              = "BARGAIN/Kalman",
  "PRED_BARGAIN_ADAPTIVE_KALMAN"     = "BARGAIN/AdaptKalman",
  "PRED_BARGAIN_LSTM_SS"             = "BARGAIN/LSTM-SS",
  "PRED_ADAPTIVE_KALMAN_WaveGate"    = "WaveGate/AdaptKalman",
  "PRED_ADAPTIVE_KALMAN_NashGate"    = "NashGate/AdaptKalman",
  "PRED_ADAPTIVE_KALMAN_MambaATSP"   = "MambaATSP/AdaptKalman",
  "PRED_LSTM_SS_WaveGate"            = "WaveGate/LSTM-SS",
  "PRED_LSTM_SS_NashGate"            = "NashGate/LSTM-SS",
  "PRED_LSTM_SS_MambaATSP"           = "MambaATSP/LSTM-SS"
)

strategies <- df %>%
  filter(experiment %in% STRAT_NAMES) %>%
  mutate(
    vs_baseline    = pass_delay_hrs - base_delay,
    pct_change     = 100 * vs_baseline / base_delay,
    strategy_label = recode(experiment, !!!STRAT_LABELS),
    ci_delay       = ci95(pass_delay_sd, n_seeds),
    ci_bus         = ci95(bus_delay_sd, n_seeds),
    ci_car         = ci95(car_delay_sd, n_seeds)
  )

# ZIG sweep (average over seeds)
zig <- df %>%
  filter(str_detect(experiment, "ZIG_SWEEP")) %>%
  mutate(
    balance = case_when(
      str_detect(experiment, "B025") ~ 0.25,
      str_detect(experiment, "B050") ~ 0.50,
      str_detect(experiment, "B075") ~ 0.75,
      str_detect(experiment, "B100") ~ 1.00,
      TRUE ~ NA_real_
    ),
    network = case_when(
      str_detect(experiment, "N30") ~ 3,
      str_detect(experiment, "N50") ~ 5,
      str_detect(experiment, "N70") ~ 7,
      TRUE ~ NA_real_
    ),
    vs_baseline = pass_delay_hrs - base_delay,
    balance_f = factor(balance),
    network_f = factor(network)
  )

n_seeds_total <- max(df_raw %>% count(experiment) %>% pull(n), na.rm = TRUE)
cat(sprintf(
  "Data loaded: %d total rows, %d experiments, up to %d seeds per experiment\n",
  nrow(df_raw), nrow(df), n_seeds_total
))
cat(sprintf("Seed-averaged: %d strategy rows, %d ZIG sweep rows\n",
    nrow(strategies), nrow(zig)))

# =====================================================================
# Figure 1: Bus lateness (NO_TSP bus delay distribution — all seeds combined)
# =====================================================================
# Glob all NO_TSP result folders to combine bus trips across seeds
bus_trips_files <- Sys.glob(file.path("results", "NO_TSP*", "bus_trips.csv"))
if (length(bus_trips_files) > 0) {
  bus_tt_all <- map_dfr(bus_trips_files, function(fp) {
    tryCatch(read_csv(fp, show_col_types = FALSE), error = function(e) NULL)
  })
  bus_tt <- bus_tt_all$TravelTime_s
  bus_tt <- bus_tt[!is.na(bus_tt) & bus_tt > 0]

  sched_tt <- as.numeric(quantile(bus_tt, 0.10))
  lateness <- bus_tt - sched_tt

  lateness_summary <- tibble(
    threshold_s   = c(10, 20, 30, 50, 60, 90, 120),
    pct_violating = sapply(threshold_s, function(th) 100 * mean(lateness > th))
  )

  p1 <- tibble(lateness = lateness) %>%
    ggplot(aes(lateness)) +
    geom_histogram(bins = 50, fill = "#4682B4", alpha = 0.85,
                   boundary = 0, color = "white", linewidth = 0.2) +
    geom_vline(xintercept = c(30, 60), linetype = "dashed",
               color = c("#D2691E", "#CD5C5C"), linewidth = 1.0) +
    annotate("text", x = 35, y = Inf, label = "30s", color = "#D2691E", vjust = 2, size = 3.5) +
    annotate("text", x = 65, y = Inf, label = "60s", color = "#CD5C5C", vjust = 2, size = 3.5) +
    labs(x = "Delay vs Scheduled (s)", y = "Number of Bus Trips",
         title = "NO_TSP Bus Delay Distribution",
         subtitle = paste0(length(bus_trips_files), " seed(s) combined | Scheduled TT: ",
                           round(sched_tt, 1), "s | Mean: ",
                           round(mean(bus_tt), 1), "s | Max: ", round(max(bus_tt), 1), "s"))

  p2 <- lateness_summary %>%
    ggplot(aes(factor(threshold_s), pct_violating)) +
    geom_col(fill = "#CD5C5C", width = 0.6) +
    geom_text(aes(label = paste0(round(pct_violating, 0), "%")),
              vjust = -0.3, color = "black", size = 3.2) +
    labs(x = "Lateness Threshold (s)", y = "% Trips Exceeding",
         title = "Lateness Violation Rate by Threshold",
         subtitle = paste0(round(mean(lateness > 30) * 100, 0), "% of trips exceed 30s; ",
                           round(mean(lateness > 60) * 100, 0), "% exceed 60s"))

  ggsave("plots/fig_lateness.pdf", p1 / p2, width = 7, height = 6.5, device = "pdf")
  cat("Saved: plots/fig_lateness.pdf\n")
} else {
  cat("Skipping fig_lateness.pdf — no bus_trips.csv files found under results/NO_TSP*/\n")
}

# =====================================================================
# Figure 2: Bus delay reduction by strategy (mean ± 95% CI)
# =====================================================================
strategies %>%
  mutate(bus_improvement_pct    = 100 * (base_bus - bus_delay_s) / base_bus,
         bus_improvement_ci_pct = 100 * ci_bus / base_bus) %>%
  arrange(desc(bus_improvement_pct)) %>%
  ggplot(aes(reorder(strategy_label, bus_improvement_pct), bus_improvement_pct,
             fill = bus_improvement_pct)) +
  geom_col(width = 0.55) +
  geom_errorbar(aes(ymin = bus_improvement_pct - bus_improvement_ci_pct,
                    ymax = bus_improvement_pct + bus_improvement_ci_pct),
                width = 0.25, color = "gray30") +
  geom_text(aes(label = paste0(round(bus_improvement_pct, 0), "%  (",
                               round(bus_delay_s, 1), "s)")),
            hjust = -0.15, color = "black", size = 3.0) +
  scale_fill_gradient(low = "#D2691E", high = "#3CB371") +
  coord_flip() +
  labs(x = "", y = "Bus Delay Reduction (%)",
       title = "Bus Delay Reduction vs NoPriority",
       subtitle = paste0("Mean ± 95% CI across ", n_seeds_total, " seed(s) | Baseline: ",
                         round(base_bus, 1), " s/pax")) +
  theme(legend.position = "none")
ggsave("plots/fig_bus_improvement.pdf", width = 8, height = 4, device = "pdf")
cat("Saved: plots/fig_bus_improvement.pdf\n")

# =====================================================================
# Figure 3: Bus vs Car tradeoff scatter (mean values, CI as cross-hairs)
# =====================================================================
strategies %>%
  filter(experiment != "NO_TSP") %>%
  mutate(lbl_vjust = case_when(str_detect(strategy_label, "WaveGate") ~ -1.2,
                                str_detect(strategy_label, "CellSearch") ~ 1.6,
                                str_detect(strategy_label, "NashGate") ~ 1.4,
                                TRUE ~ -1.2),
         lbl_hjust = 0.5) %>%
  ggplot(aes(bus_delay_s, car_delay_s, label = strategy_label)) +
  annotate("rect", xmin = -Inf, xmax = base_bus, ymin = -Inf, ymax = base_car,
           fill = "#3CB371", alpha = 0.08) +
  geom_vline(xintercept = base_bus, linetype = "dashed", color = "#4682B4", alpha = 0.5) +
  geom_hline(yintercept = base_car, linetype = "dashed", color = "#D2691E", alpha = 0.5) +
  annotate("text", x = base_bus - 4, y = base_car - 2,
           label = "Both better", color = "#3CB371", size = 3.5, hjust = 1) +
  # CI cross-hairs
  geom_errorbar(aes(ymin = car_delay_s - ci_car, ymax = car_delay_s + ci_car),
                width = 0.3, alpha = 0.4, color = "gray50") +
  geom_errorbarh(aes(xmin = bus_delay_s - ci_bus, xmax = bus_delay_s + ci_bus),
                 height = 0.3, alpha = 0.4, color = "gray50") +
  geom_point(aes(size = grant_rate, color = pass_delay_hrs), alpha = 0.9) +
  geom_text(aes(vjust = lbl_vjust, hjust = lbl_hjust), color = "black", size = 2.8) +
  scale_color_viridis_c(name = "Total Delay (hrs)") +
  scale_size_continuous(name = "Grant Rate", labels = percent_format()) +
  labs(x = "Bus Delay (s/pax)", y = "Car Delay (s/pax)",
       title = "Bus vs Car Tradeoff by Strategy",
       subtitle = paste0("Mean ± 95% CI across ", n_seeds_total, " seed(s). ",
                         "Green zone = both better than NoPriority.")) +
  theme(legend.position = "right")
ggsave("plots/fig_bus_vs_car.pdf", width = 8.5, height = 6.5, device = "pdf")
cat("Saved: plots/fig_bus_vs_car.pdf\n")

# =====================================================================
# Figure 4: WaveGate sweep heatmap (seed-averaged)
# =====================================================================
if (nrow(zig) > 0) {
  zig %>%
    ggplot(aes(balance_f, network_f, fill = pass_delay_hrs)) +
    geom_tile(color = "white", linewidth = 2) +
    geom_text(aes(label = paste0(round(pass_delay_hrs, 0), " h\nbus:",
                                 round(bus_delay_s, 1), "s | car:", round(car_delay_s, 1), "s")),
              color = "white", size = 3.5, lineheight = 0.9) +
    scale_fill_viridis_c(name = "Total Pax Delay (hrs)", option = "D") +
    labs(x = "Balance Factor (higher = more bus priority)",
         y = "Network Factor (higher = more car protection)",
         title = "WaveGate: Gate Threshold × Cross-Traffic Penalty",
         subtitle = paste0("Seed-averaged (", n_seeds_total, " seeds) | Baseline: ",
                           round(base_delay, 0), "h"))
  ggsave("plots/fig_zig_heatmap.pdf", width = 8.5, height = 5, device = "pdf")
  cat("Saved: plots/fig_zig_heatmap.pdf\n")

  # =====================================================================
  # Figure 5: WaveGate swept total delay grouped bar (seed-averaged)
  # =====================================================================
  zig %>%
    ggplot(aes(balance_f, pass_delay_hrs, fill = network_f)) +
    geom_col(position = "dodge", width = 0.7) +
    geom_text(aes(label = round(pass_delay_hrs, 0)),
              position = position_dodge(0.7), vjust = -0.3, size = 3, color = "black") +
    geom_hline(yintercept = base_delay, linetype = "dashed", color = "#CD5C5C", linewidth = 1.0) +
    annotate("text", x = Inf, y = base_delay,
             label = paste0("NO_TSP: ", round(base_delay, 0)),
             hjust = 1.05, vjust = -1, color = "#CD5C5C", size = 3.5) +
    scale_fill_viridis_d(name = "Network\nFactor", option = "D") +
    labs(x = "Balance Factor", y = "Total Passenger Delay (hrs)",
         title = "WaveGate Parameter Sweep: Total Delay (seed-averaged)",
         subtitle = paste0("Averaged across ", n_seeds_total, " seeds"))
  ggsave("plots/fig_zig_total.pdf", width = 8, height = 4.5, device = "pdf")
  cat("Saved: plots/fig_zig_total.pdf\n")
} else {
  cat("Skipping ZIG sweep plots — no ZIG_SWEEP experiments in batch_results.csv\n")
}

# =====================================================================
# Figure 6: Main vs Side corridor delay split (mean ± 95% CI)
# =====================================================================
strategies %>%
  select(strategy_label, main_delay_hrs, side_delay_hrs,
         main_delay_sd, side_delay_sd, n_seeds) %>%
  mutate(
    main_ci = ci95(main_delay_sd, n_seeds),
    side_ci = ci95(side_delay_sd, n_seeds)
  ) %>%
  pivot_longer(c(main_delay_hrs, side_delay_hrs), names_to = "section", values_to = "hrs") %>%
  mutate(
    section = ifelse(section == "main_delay_hrs", "Main Corridor", "Side Streets"),
    ci = ifelse(section == "Main Corridor", main_ci, side_ci)
  ) %>%
  ggplot(aes(reorder(strategy_label, hrs), hrs, fill = section)) +
  geom_col(position = "stack", width = 0.55) +
  coord_flip() +
  scale_fill_manual(values = c("Main Corridor" = "#6A5ACD", "Side Streets" = "#3CB371")) +
  labs(x = "", y = "Passenger Delay (hrs)", fill = "",
       title = "Delay Split: Main Corridor vs Side Streets",
       subtitle = paste0("Mean across ", n_seeds_total, " seed(s). TSP shifts delay between corridor and cross-streets."))
ggsave("plots/fig_main_side.pdf", width = 7.5, height = 4, device = "pdf")
cat("Saved: plots/fig_main_side.pdf\n")

cat(sprintf("\nAll plots generated in plots/ directory (%d seeds averaged).\n", n_seeds_total))
