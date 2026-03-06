import time

class MetricsCollector:
    def __init__(self):
        self.incident_start = {}
        self.mttr_values = []
        self.rca_total = 0
        self.rca_correct = 0

    def start_incident(self, incident_id):
        self.incident_start[incident_id] = time.time()

    def end_incident(self, incident_id):
        if incident_id in self.incident_start:
            mttr = time.time() - self.incident_start[incident_id]
            self.mttr_values.append(mttr)
            del self.incident_start[incident_id]

    def record_rca(self, predicted, actual):
        self.rca_total += 1
        if predicted == actual:
            self.rca_correct += 1

    def report(self):
        avg_mttr = sum(self.mttr_values) / len(self.mttr_values) if self.mttr_values else 0
        rca_acc = (self.rca_correct / self.rca_total) * 100 if self.rca_total else 0

        return {
            "average_mttr_seconds": round(avg_mttr, 2),
            "root_cause_accuracy_percent": round(rca_acc, 2),
            "incidents": len(self.mttr_values)
        }

metrics = MetricsCollector()