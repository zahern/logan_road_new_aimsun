# generate_paper_plots.R
# Produces paper-quality plots for TSP_Paper.tex from batch_results.csv
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

df <- batch %>% 
  rename(
    experiment = run_experiment,
    seed      = run_seed,
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

# Baseline
no_tsp <- df %>% filter(experiment == "NO_TSP")
base_delay <- no_tsp$pass_delay_hrs[1]
base_bus   <- no_tsp$bus_delay_s[1]
base_car   <- no_tsp$car_delay_s[1]

# Strategy subset
strategies <- df %>%
  filter(experiment %in% c("NO_TSP","DCTSP_MARL","DCTSP_MARL_HS",
         "DCTSP_ZIG","DCTSP_BARGAIN_SPM","DCTSP_MP_ECTM","DCTSP_BXT")) %>%
  mutate(
    vs_baseline = pass_delay_hrs - base_delay,
    pct_change  = 100 * vs_baseline / base_delay,
    strategy_label = case_when(
      experiment == "NO_TSP"             ~ "NoPriority",
      experiment == "DCTSP_MARL"         ~ "CPD-QL",
      experiment == "DCTSP_MARL_HS"      ~ "CPD-QL-HS",
      experiment == "DCTSP_ZIG"          ~ "WaveGate",
      experiment == "DCTSP_BARGAIN_SPM"  ~ "NashGate",
      experiment == "DCTSP_MP_ECTM"      ~ "CellSearch",
      experiment == "DCTSP_BXT"          ~ "CellQLearn",
      TRUE ~ experiment
    )
  )

# ZIG sweep
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

cat(sprintf("Data loaded: %d total rows, %d strategies, %d ZIG sweep points\n",
    nrow(df), nrow(strategies), nrow(zig)))

# =====================================================================
# Figure 1: Bus lateness (NO_TSP bus delay distribution)
# =====================================================================
bus_trips_path <- "results/NO_TSP_seed300_11129236_11129237_11129240/bus_trips.csv"
if(file.exists(bus_trips_path)) {
  bus_tt <- read_csv(bus_trips_path, show_col_types = FALSE)$TravelTime_s
  bus_tt <- bus_tt[!is.na(bus_tt) & bus_tt > 0]
  sched_tt <- as.numeric(quantile(bus_tt, 0.10))
  lateness <- bus_tt - sched_tt
  
  lateness_summary <- tibble(
    threshold_s = c(10, 20, 30, 50, 60, 90, 120),
    pct_violating = sapply(threshold_s, function(th) 100 * mean(lateness > th))
  )
  
  p1 <- tibble(lateness = lateness) %>%
    ggplot(aes(lateness)) +
    geom_histogram(bins = 50, fill = "#4682B4", alpha = 0.85,
                   boundary = 0, color = "white", size = 0.2) +
    geom_vline(xintercept = c(30, 60), linetype = "dashed", 
               color = c("#D2691E", "#CD5C5C"), size = 1.0) +
    annotate("text", x = 35, y = Inf, label = "30s", color = "#D2691E", vjust = 2, size = 3.5) +
    annotate("text", x = 65, y = Inf, label = "60s", color = "#CD5C5C", vjust = 2, size = 3.5) +
    labs(x = "Delay vs Scheduled (s)", y = "Number of Bus Trips",
         title = "NO_TSP Bus Delay Distribution",
         subtitle = paste0("Scheduled TT: ", round(sched_tt, 1), "s | Mean: ", 
                           round(mean(bus_tt), 1), "s | Max: ", round(max(bus_tt), 1), "s"))
  
  p2 <- lateness_summary %>%
    ggplot(aes(factor(threshold_s), pct_violating)) +
    geom_col(fill = "#CD5C5C", width = 0.6) +
    geom_text(aes(label = paste0(round(pct_violating, 0), "%")),
              vjust = -0.3, color = "black", size = 3.2) +
    labs(x = "Lateness Threshold (s)", y = "% Trips Exceeding",
         title = "Lateness Violation Rate by Threshold",
         subtitle = paste0(round(mean(lateness>30)*100, 0), "% of trips exceed 30s; ",
                           round(mean(lateness>60)*100, 0), "% exceed 60s"))
  
  ggsave("plots/fig_lateness.pdf", p1 / p2, width = 7, height = 6.5, device = "pdf")
  cat("Saved: plots/fig_lateness.pdf\n")
}

# =====================================================================
# Figure 2: Bus delay reduction by strategy
# =====================================================================
strategies %>%
  mutate(bus_improvement_pct = 100 * (base_bus - bus_delay_s) / base_bus) %>%
  arrange(desc(bus_improvement_pct)) %>%
  ggplot(aes(reorder(strategy_label, bus_improvement_pct), bus_improvement_pct, 
             fill = bus_improvement_pct)) +
  geom_col(width = 0.55) +
  geom_text(aes(label = paste0(round(bus_improvement_pct, 0), "%  (", round(bus_delay_s, 1), "s)")),
            hjust = -0.1, color = "black", size = 3.2) +
  scale_fill_gradient(low = "#D2691E", high = "#3CB371") +
  coord_flip() +
  labs(x = "", y = "Bus Delay Reduction (%)",
       title = "Bus Delay Reduction vs NoPriority",
       subtitle = paste0("Baseline NoPriority bus delay: ", round(base_bus, 1), " s/pax")) +
  theme(legend.position = "none")
ggsave("plots/fig_bus_improvement.pdf", width = 7, height = 3.5, device = "pdf")
cat("Saved: plots/fig_bus_improvement.pdf\n")

# =====================================================================
# Figure 3: Bus vs Car tradeoff scatter
# =====================================================================
strategies %>%
  filter(experiment != "NO_TSP") %>%
  mutate(lbl_vjust = case_when(strategy_label == "WaveGate" ~ -1.2,
                                strategy_label == "CellSearch" ~ 1.6,
                                strategy_label == "NashGate" ~ 1.4,
                                TRUE ~ -1.2),
         lbl_hjust = case_when(strategy_label == "WaveGate" ~ -0.1,
                                strategy_label == "NashGate" ~ -0.1,
                                TRUE ~ 0.5)) %>%
  ggplot(aes(bus_delay_s, car_delay_s, label = strategy_label)) +
  annotate("rect", xmin = -Inf, xmax = base_bus, ymin = -Inf, ymax = base_car,
           fill = "#3CB371", alpha = 0.08) +
  geom_vline(xintercept = base_bus, linetype = "dashed", color = "#4682B4", alpha = 0.5) +
  geom_hline(yintercept = base_car, linetype = "dashed", color = "#D2691E", alpha = 0.5) +
  annotate("text", x = base_bus - 4, y = base_car - 2,
           label = "Both better", color = "#3CB371", size = 3.5, hjust = 1) +
  geom_point(aes(size = grant_rate, color = pass_delay_hrs), alpha = 0.9) +
  geom_text(aes(vjust = lbl_vjust, hjust = lbl_hjust), color = "black", size = 3.2) +
  scale_color_viridis_c(name = "Total Delay (hrs)") +
  scale_size_continuous(name = "Grant Rate", labels = percent_format()) +
  labs(x = "Bus Delay (s/pax)", y = "Car Delay (s/pax)",
       title = "Bus vs Car Tradeoff by Strategy",
       subtitle = "Green zone = both better than NoPriority baseline. Dashed lines = baseline.") +
  theme(legend.position = "right")
ggsave("plots/fig_bus_vs_car.pdf", width = 8, height = 6.5, device = "pdf")
cat("Saved: plots/fig_bus_vs_car.pdf\n")

# =====================================================================
# Figure 4: WaveGate sweep heatmap (clearer labels)
# =====================================================================
zig %>%
  ggplot(aes(balance_f, network_f, fill = pass_delay_hrs)) +
  geom_tile(color = "white", size = 2) +
  geom_text(aes(label = paste0(round(pass_delay_hrs,0), " h\nbus:", round(bus_delay_s,1),
                                "s | car:", round(car_delay_s,1), "s")),
            color = "white", size = 3.5, lineheight = 0.9) +
  scale_fill_viridis_c(name = "Total Pax Delay (hrs)", option = "D") +
  labs(x = "Balance Factor (higher = more bus priority → easier to grant)",
       y = "Network Factor (higher = more car protection → harder to grant)",
       title = "WaveGate: Gate Threshold × Cross-Traffic Penalty",
       subtitle = paste0("Baseline: ", round(base_delay, 0), "h | bus ", round(base_bus, 1), "s | car ", round(base_car, 1), "s"))
ggsave("plots/fig_zig_heatmap.pdf", width = 8.5, height = 5, device = "pdf")
cat("Saved: plots/fig_zig_heatmap.pdf\n")

# =====================================================================
# Figure 5: WaveGate swept total delay grouped bar
# =====================================================================
zig %>%
  ggplot(aes(balance_f, pass_delay_hrs, fill = network_f)) +
  geom_col(position = "dodge", width = 0.7) +
  geom_text(aes(label = round(pass_delay_hrs, 0)),
            position = position_dodge(0.7), vjust = -0.3, size = 3, color = "black") +
  geom_hline(yintercept = base_delay, linetype = "dashed", color = "#CD5C5C", size = 1.0) +
  annotate("text", x = Inf, y = base_delay, label = paste0("NO_TSP: ", round(base_delay, 0)),
           hjust = 1.05, vjust = -1, color = "#CD5C5C", size = 3.5) +
  scale_fill_viridis_d(name = "Network\nFactor\n(higher =\nmore car\nprotection)", option = "D") +
  labs(x = "Balance Factor (higher = more permissive)", y = "Total Passenger Delay (hrs)",
       title = "WaveGate Parameter Sweep: Total Delay",
       subtitle = "Higher Balance + lower Network Factor = best. B1.00 N3 is best overall.")
ggsave("plots/fig_zig_total.pdf", width = 8, height = 4.5, device = "pdf")
cat("Saved: plots/fig_zig_total.pdf\n")

# =====================================================================
# Figure 6: Main vs Side corridor delay split
# =====================================================================
strategies %>%
  select(strategy_label, main_delay_hrs, side_delay_hrs) %>%
  pivot_longer(-strategy_label, names_to = "section", values_to = "hrs") %>%
  mutate(section = ifelse(section == "main_delay_hrs", "Main Corridor", "Side Streets")) %>%
  ggplot(aes(reorder(strategy_label, hrs), hrs, fill = section)) +
  geom_col(position = "stack", width = 0.55) +
  coord_flip() +
  scale_fill_manual(values = c("Main Corridor" = "#6A5ACD", "Side Streets" = "#3CB371")) +
  labs(x = "", y = "Passenger Delay (hrs)", fill = "",
       title = "Delay Split: Main Corridor vs Side Streets",
       subtitle = "TSP shifts delay between corridor and cross-streets")
ggsave("plots/fig_main_side.pdf", width = 7, height = 3.5, device = "pdf")
cat("Saved: plots/fig_main_side.pdf\n")

cat("\nAll plots generated in plots/ directory.\n")
