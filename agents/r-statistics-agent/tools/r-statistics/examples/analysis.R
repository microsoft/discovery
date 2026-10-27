data <- read.csv("/input/observations.csv")
if (!all(c("x", "y") %in% names(data))) {
  stop("Input must contain x and y columns.")
}
if (!is.numeric(data$x) || !is.numeric(data$y) ||
    any(!is.finite(data$x)) || any(!is.finite(data$y))) {
  stop("x and y must contain only finite numeric values; no rows were removed.")
}
if (nrow(data) < 3L || length(unique(data$x)) < 2L) {
  stop("Regression requires at least three observations and two distinct x values.")
}

fit <- lm(y ~ x, data = data, na.action = na.fail)
coefficients <- cbind(
  term = rownames(coef(summary(fit))),
  as.data.frame(coef(summary(fit))),
  as.data.frame(confint(fit))
)
write.csv(coefficients, "/output/coefficients.csv", row.names = FALSE)
capture.output(summary(fit), file = "/output/model-summary.txt")
capture.output(sessionInfo(), file = "/output/session-info.txt")
if (!file.copy("/analysis.R", "/output/analysis.R", overwrite = TRUE)) {
  stop("Could not save the executed analysis script.")
}

png("/output/scatter.png", width = 800, height = 600, type = "cairo")
plot(data$x, data$y, xlab = "x", ylab = "y", main = "Example linear regression")
abline(fit, col = "blue")
dev.off()

png("/output/diagnostics.png", width = 1000, height = 1000, type = "cairo")
par(mfrow = c(2, 2))
plot(fit)
dev.off()

cat(sprintf("Analyzed %d rows; slope = %.3f. Outputs: /output\n",
            nrow(data), coef(fit)[["x"]]))
