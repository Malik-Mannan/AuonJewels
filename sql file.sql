use railway;
CREATE TABLE IF NOT EXISTS reviews (
    ID INT AUTO_INCREMENT PRIMARY KEY,
    product_id INT NOT NULL,
    customer_id INT,
    customer_name VARCHAR(100),
    rating INT,
    comment TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (product_id) REFERENCES Products(ID) ON DELETE CASCADE
);